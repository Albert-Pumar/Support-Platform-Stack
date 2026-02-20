"""
Ticket Ingestion Service
=========================
The core pipeline that turns an incoming email into a structured ticket.

Flow:
  1. Receive parsed email dict from graph_service
  2. Check for duplicates (idempotent via outlook_message_id)
  3. Check if this is a new ticket OR a reply to an existing thread
  4. Create/update ticket + message in DB
  5. Trigger async enrichment + AI pipeline (via Celery)
  6. Broadcast update to connected frontend clients (via WebSocket manager)
"""

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Ticket, Message, TicketStatus, TicketPriority,
    MessageDirection, MessageSource
)
#from app.schemas.tickets import TicketCreate
from app.services import ws_manager

log = structlog.get_logger(__name__)


# ── Main Ingestion Entry Point ─────────────────────────────────────────────────

async def ingest_email(parsed_email: dict[str, Any], db: AsyncSession) -> Ticket | None:
    """
    Process an incoming email and create or update a ticket.

    This function is idempotent: calling it twice with the same email
    (same outlook_message_id) will not create duplicate records.

    Returns the ticket (new or existing) or None if the email should be ignored.
    """
    log.info(
        "ingestion.start",
        outlook_message_id=parsed_email["outlook_message_id"],
        conversation_id=parsed_email["outlook_conversation_id"],
        sender=parsed_email["sender_email"],
    )

    # ── Step 1: Deduplication ──────────────────────────────────────────────────
    # Graph API webhooks can fire more than once for the same message.
    # We use outlook_message_id as the dedup key.
    existing_message = await db.scalar(
        select(Message).where(Message.outlook_message_id == parsed_email["outlook_message_id"])
    )
    if existing_message:
        log.info("ingestion.duplicate_skipped", outlook_message_id=parsed_email["outlook_message_id"])
        return None

    # ── Step 2: Check if this is a new thread or a reply ──────────────────────
    conversation_id = parsed_email["outlook_conversation_id"]
    existing_ticket = None

    if conversation_id:
        existing_ticket = await db.scalar(
            select(Ticket).where(Ticket.outlook_conversation_id == conversation_id)
        )

    if existing_ticket:
        # ── Path A: Reply to existing ticket ──────────────────────────────────
        log.info("ingestion.reply", ticket_id=str(existing_ticket.id))
        await _add_message_to_ticket(existing_ticket, parsed_email, db)
        # Reopen ticket if it was resolved (user replied after resolution)
        if existing_ticket.status == TicketStatus.resolved:
            existing_ticket.status = TicketStatus.open
            log.info("ingestion.ticket_reopened", ticket_id=str(existing_ticket.id))
        return existing_ticket
    else:
        # ── Path B: New ticket ─────────────────────────────────────────────────
        log.info("ingestion.new_ticket", sender=parsed_email["sender_email"])
        ticket = await _create_ticket(parsed_email, db)
        return ticket


# ── Ticket Creation ────────────────────────────────────────────────────────────

async def _create_ticket(parsed_email: dict[str, Any], db: AsyncSession) -> Ticket:
    """Create a new ticket and its first message."""

    # Auto-increment ticket number (human-readable SF-XXXX)
    max_number = await db.scalar(select(func.max(Ticket.ticket_number))) or 1000
    ticket_number = max_number + 1

    ticket = Ticket(
        id=uuid.uuid4(),
        ticket_number=ticket_number,
        subject=_clean_subject(parsed_email["subject"]),
        status=TicketStatus.open,
        priority=TicketPriority.medium,
        category=None,  # Will be set by AI pipeline
        sender_email=parsed_email["sender_email"],
        sender_name=parsed_email["sender_name"],
        detected_language=None,  # Will be set by AI pipeline
        outlook_conversation_id=parsed_email["outlook_conversation_id"],
        outlook_internet_message_id=parsed_email["internet_message_id"],
        tags=[],
    )
    db.add(ticket)
    await db.flush()  # Get the ID without committing

    # Add the first message
    await _add_message_to_ticket(ticket, parsed_email, db)

    log.info(
        "ingestion.ticket_created",
        ticket_id=str(ticket.id),
        display_id=ticket.display_id,
        sender=ticket.sender_email,
    )

    # Dispatch async tasks (non-blocking)
    await _dispatch_async_tasks(ticket)

    return ticket


async def _add_message_to_ticket(
    ticket: Ticket,
    parsed_email: dict[str, Any],
    db: AsyncSession,
) -> Message:
    """Add an inbound email as a message in the ticket thread."""

    message = Message(
        id=uuid.uuid4(),
        ticket_id=ticket.id,
        sender_email=parsed_email["sender_email"],
        sender_name=parsed_email["sender_name"],
        body_html=parsed_email["body_html"],
        body_text=parsed_email["body_text"],
        direction=MessageDirection.inbound,
        source=MessageSource.outlook,
        outlook_message_id=parsed_email["outlook_message_id"],
        raw_headers=parsed_email.get("raw_headers"),
    )
    db.add(message)

    # Update ticket's updated_at timestamp
    ticket.updated_at = datetime.now(timezone.utc)

    # Broadcast real-time update to connected frontend clients
    await ws_manager.broadcast_ticket_update(str(ticket.id), {
        "event": "new_message",
        "ticket_id": str(ticket.id),
        "display_id": ticket.display_id,
        "message_id": str(message.id),
    })

    return message


# ── Outbound Reply ─────────────────────────────────────────────────────────────

async def record_outbound_reply(
    ticket: Ticket,
    body_html: str,
    body_text: str,
    agent_email: str,
    agent_name: str,
    db: AsyncSession,
) -> Message:
    """
    Record an outbound reply sent from the platform.
    The actual Graph API send is handled in the router — this just
    saves the message to our DB so the thread stays in sync.
    """
    message = Message(
        id=uuid.uuid4(),
        ticket_id=ticket.id,
        sender_email=agent_email,
        sender_name=agent_name,
        body_html=body_html,
        body_text=body_text,
        direction=MessageDirection.outbound,
        source=MessageSource.platform,
        outlook_message_id=None,  # Will be updated after Graph API confirms send
    )
    db.add(message)
    ticket.updated_at = datetime.now(timezone.utc)

    await ws_manager.broadcast_ticket_update(str(ticket.id), {
        "event": "new_message",
        "ticket_id": str(ticket.id),
        "display_id": ticket.display_id,
        "message_id": str(message.id),
    })

    return message


# ── Async Task Dispatch ────────────────────────────────────────────────────────

async def _dispatch_async_tasks(ticket: Ticket) -> None:
    """
    Fire-and-forget: queue background tasks for a new ticket.
    These run in Celery workers and don't block the webhook response.
    """
    try:
        from app.workers.tasks import task_run_ai_pipeline, task_enrich_ticket
        # Enrich and pipeline run in parallel — pipeline uses enrichment if it arrives in time
        task_enrich_ticket.delay(str(ticket.id))
        task_run_ai_pipeline.delay(str(ticket.id))
        log.info("ingestion.tasks_dispatched", ticket_id=str(ticket.id))
    except Exception as e:
        log.error("ingestion.task_dispatch_failed", ticket_id=str(ticket.id), error=str(e))


# ── Helpers ────────────────────────────────────────────────────────────────────

def _clean_subject(subject: str) -> str:
    """Strip common email prefixes like RE:, FWD:, AW:, WG: etc."""
    import re
    prefixes = r"^(re|fwd|fw|aw|wg|sv|tr|ref)[\s]*:[\s]*"
    while re.match(prefixes, subject, re.IGNORECASE):
        subject = re.sub(prefixes, "", subject, flags=re.IGNORECASE).strip()
    return subject or "(no subject)"
