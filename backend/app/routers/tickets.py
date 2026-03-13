"""
Tickets Router
===============
REST API for the support platform frontend.
"""

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.models import (
    Ticket, Message, TicketStatus, MessageDirection, MessageSource
)
from app.services.graph_service import send_reply
from app.services.ingestion_service import record_outbound_reply
from app.services.ws_manager import ws_manager

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/tickets", tags=["tickets"])


# ── List Tickets ───────────────────────────────────────────────────────────────

@router.get("")
async def list_tickets(
    status: TicketStatus | None = None,
    assignee_id: uuid.UUID | None = None,
    category: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    query = (
        select(Ticket)
        .options(selectinload(Ticket.assignee), selectinload(Ticket.messages))
        .order_by(desc(Ticket.updated_at))
        .limit(limit)
        .offset(offset)
    )
    if status:
        query = query.where(Ticket.status == status)
    if assignee_id:
        query = query.where(Ticket.assignee_id == assignee_id)

    result = await db.execute(query)
    tickets = result.scalars().all()

    return {
        "tickets": [_serialize_ticket(t) for t in tickets],
        "total": len(tickets),
    }


# ── Get Single Ticket (with full thread) ──────────────────────────────────────

@router.get("/{ticket_id}")
async def get_ticket(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    ticket = await db.scalar(
        select(Ticket)
        .where(Ticket.id == ticket_id)
        .options(
            selectinload(Ticket.assignee),
            selectinload(Ticket.messages),
            selectinload(Ticket.enrichment),
            selectinload(Ticket.ai_draft),
        )
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    return _serialize_ticket(ticket, full=True)


# ── Reply to Ticket ────────────────────────────────────────────────────────────

@router.post("/{ticket_id}/reply")
async def reply_to_ticket(
    ticket_id: uuid.UUID,
    body: dict[str, str],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Send a reply from the support platform.

    Flow:
    1. Find the latest inbound message (to reply to in the correct thread)
    2. Send via Graph API (appears in Outlook thread)
    3. Record in our DB
    4. Broadcast via WebSocket
    """
    ticket = await db.scalar(
        select(Ticket)
        .where(Ticket.id == ticket_id)
        .options(selectinload(Ticket.messages))
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    reply_html = body.get("body_html", "")
    reply_text = body.get("body_text", reply_html)
    agent_name = body.get("agent_name", "Support Agent")
    agent_email = body.get("agent_email", "agent@support.ch")

    if not reply_html:
        raise HTTPException(status_code=422, detail="body_html is required")

    # Find the latest message with an Outlook ID to reply to
    latest_outlook_message = next(
        (
            m for m in sorted(ticket.messages, key=lambda m: m.created_at, reverse=True)
            if m.outlook_message_id
        ),
        None,
    )

    if not latest_outlook_message:
        raise HTTPException(
            status_code=400,
            detail="No Outlook message ID found — cannot send via Graph API",
        )

    # ── Send via Graph API ─────────────────────────────────────────────────────
    try:
        await send_reply(
            original_message_id=latest_outlook_message.outlook_message_id,
            body_html=reply_html,
            sender_name=agent_name,
        )
    except Exception as e:
        log.error("reply.graph_send_failed", ticket_id=str(ticket_id), error=str(e))
        raise HTTPException(status_code=502, detail=f"Graph API send failed: {e}")

    # ── Record in DB ───────────────────────────────────────────────────────────
    message = await record_outbound_reply(
        ticket=ticket,
        body_html=reply_html,
        body_text=reply_text,
        agent_email=agent_email,
        agent_name=agent_name,
        db=db,
    )

    # Update ticket status to pending (waiting for user reply)
    ticket.status = TicketStatus.pending
    await db.commit()

    log.info("reply.sent", ticket_id=str(ticket_id), message_id=str(message.id))

    return {
        "message_id": str(message.id),
        "ticket_id": str(ticket_id),
        "status": "sent",
    }


# ── Update Ticket (status, assignee, priority) ────────────────────────────────

@router.patch("/{ticket_id}")
async def update_ticket(
    ticket_id: uuid.UUID,
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    ticket = await db.scalar(select(Ticket).where(Ticket.id == ticket_id))
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    allowed_fields = {"status", "priority", "assignee_id", "category", "tags"}
    for field, value in body.items():
        if field in allowed_fields:
            setattr(ticket, field, value)

    await db.commit()
    await ws_manager.broadcast_ticket_update(str(ticket_id), {
        "event": "ticket_updated",
        "ticket_id": str(ticket_id),
        "changes": body,
    })

    return {"ticket_id": str(ticket_id), "updated": list(body.keys())}


# ── WebSocket: Real-time updates ───────────────────────────────────────────────

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Global WebSocket — receives updates for all tickets."""
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # Keep-alive (ignore client messages)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


@router.websocket("/{ticket_id}/ws")
async def ticket_websocket(websocket: WebSocket, ticket_id: str):
    """Per-ticket WebSocket — receives updates only for one ticket."""
    await ws_manager.connect(websocket, ticket_id=ticket_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, ticket_id=ticket_id)


# ── Serializers ────────────────────────────────────────────────────────────────

def _serialize_ticket(ticket: Ticket, full: bool = False) -> dict[str, Any]:
    base = {
        "id": str(ticket.id),
        "display_id": ticket.display_id,
        "subject": ticket.subject,
        "status": ticket.status,
        "priority": ticket.priority,
        "category": ticket.category,
        "sender_email": ticket.sender_email,
        "sender_name": ticket.sender_name,
        "detected_language": ticket.detected_language,
        "tags": ticket.tags or [],
        "assignee": {
            "id": str(ticket.assignee.id),
            "name": ticket.assignee.name,
            "email": ticket.assignee.email,
        } if ticket.assignee else None,
        "message_count": len(ticket.messages) if ticket.messages else 0,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
    }

    if full:
        base["messages"] = [
            {
                "id": str(m.id),
                "sender_email": m.sender_email,
                "sender_name": m.sender_name,
                "body_text": m.body_text,
                "body_html": m.body_html,
                "direction": m.direction,
                "source": m.source,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in (ticket.messages or [])
        ]
        if ticket.enrichment:
            base["enrichment"] = {
                "sf_user_data": ticket.enrichment.sf_user_data,
                "sentry_events": ticket.enrichment.sentry_events,
                "posthog_recordings": ticket.enrichment.posthog_recordings,
                "similar_tickets": ticket.enrichment.similar_tickets,
                "fetched_at": ticket.enrichment.fetched_at.isoformat(),
            }
        if ticket.ai_draft:
            base["ai_draft"] = {
                "id": str(ticket.ai_draft.id),
                "draft_body": ticket.ai_draft.draft_body,
                "confidence": ticket.ai_draft.confidence,
                "model_used": ticket.ai_draft.model_used,
            }

    return base
