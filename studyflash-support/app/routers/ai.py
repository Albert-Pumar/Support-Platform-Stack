"""
AI Router
==========
Endpoints for interacting with the AI pipeline from the frontend:
  - POST /tickets/{id}/ai/regenerate   → trigger draft regeneration (with optional feedback)
  - POST /tickets/{id}/ai/draft/accept → mark draft as accepted (feedback loop)
  - POST /tickets/{id}/ai/draft/reject → mark draft as rejected
  - POST /tickets/{id}/ai/classify     → manually re-run classification
  - GET  /ai/stats                     → cost and usage stats for the team dashboard
"""

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import Ticket, AIDraft

log = structlog.get_logger(__name__)
router = APIRouter(tags=["ai"])


# ── Request/Response Models ────────────────────────────────────────────────────

class RegenerateRequest(BaseModel):
    feedback: str | None = None  # e.g. "make it shorter", "add refund timeline"


class DraftFeedbackRequest(BaseModel):
    was_edited: bool = False
    final_body: str | None = None  # The actual text sent (for quality tracking)


# ── Regenerate Draft ───────────────────────────────────────────────────────────

@router.post("/tickets/{ticket_id}/ai/regenerate")
async def regenerate_draft(
    ticket_id: uuid.UUID,
    body: RegenerateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Trigger async draft regeneration.
    Returns immediately — frontend gets the new draft via WebSocket event 'draft_regenerated'.
    """
    ticket = await db.scalar(select(Ticket).where(Ticket.id == ticket_id))
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    from app.workers.tasks import task_regenerate_draft
    background_tasks.add_task(
        lambda: task_regenerate_draft.delay(str(ticket_id), body.feedback)
    )

    log.info("ai.regenerate.queued", ticket_id=str(ticket_id), feedback=body.feedback)
    return {"status": "queued", "ticket_id": str(ticket_id)}


# ── Draft Feedback (accept/reject) ─────────────────────────────────────────────

@router.post("/tickets/{ticket_id}/ai/draft/accept")
async def accept_draft(
    ticket_id: uuid.UUID,
    body: DraftFeedbackRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Agent accepted the AI draft (sent it as-is or with edits).
    This feedback is stored for quality tracking and future fine-tuning.
    """
    draft = await db.scalar(
        select(AIDraft).where(AIDraft.ticket_id == ticket_id)
    )
    if not draft:
        raise HTTPException(status_code=404, detail="No draft found for this ticket")

    draft.was_accepted = True
    draft.was_edited = body.was_edited
    await db.commit()

    log.info(
        "ai.draft.accepted",
        ticket_id=str(ticket_id),
        was_edited=body.was_edited,
    )
    return {"status": "recorded", "was_accepted": True, "was_edited": body.was_edited}


@router.post("/tickets/{ticket_id}/ai/draft/reject")
async def reject_draft(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Agent rejected the draft entirely and wrote their own reply.
    """
    draft = await db.scalar(
        select(AIDraft).where(AIDraft.ticket_id == ticket_id)
    )
    if not draft:
        raise HTTPException(status_code=404, detail="No draft found for this ticket")

    draft.was_accepted = False
    await db.commit()

    log.info("ai.draft.rejected", ticket_id=str(ticket_id))
    return {"status": "recorded", "was_accepted": False}


# ── Manual Re-classify ─────────────────────────────────────────────────────────

@router.post("/tickets/{ticket_id}/ai/classify")
async def reclassify_ticket(
    ticket_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Manually re-run the full AI pipeline for a ticket.
    Useful when an agent disagrees with the auto-classification.
    """
    ticket = await db.scalar(select(Ticket).where(Ticket.id == ticket_id))
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    from app.workers.tasks import task_run_ai_pipeline
    background_tasks.add_task(
        lambda: task_run_ai_pipeline.delay(str(ticket_id))
    )

    log.info("ai.reclassify.queued", ticket_id=str(ticket_id))
    return {"status": "queued", "ticket_id": str(ticket_id)}


# ── AI Usage Stats ─────────────────────────────────────────────────────────────

@router.get("/ai/stats")
async def get_ai_stats(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    AI usage and quality stats for the team dashboard.
    Shows acceptance rate, cost, and volume over time.
    """
    # Total drafts generated
    total_drafts = await db.scalar(select(func.count(AIDraft.id))) or 0

    # Acceptance breakdown
    accepted = await db.scalar(
        select(func.count(AIDraft.id)).where(AIDraft.was_accepted == True)
    ) or 0
    rejected = await db.scalar(
        select(func.count(AIDraft.id)).where(AIDraft.was_accepted == False)
    ) or 0
    accepted_with_edits = await db.scalar(
        select(func.count(AIDraft.id))
        .where(AIDraft.was_accepted == True)
        .where(AIDraft.was_edited == True)
    ) or 0
    pending = total_drafts - accepted - rejected

    # Token consumption
    total_prompt_tokens = await db.scalar(
        select(func.sum(AIDraft.prompt_tokens))
    ) or 0
    total_completion_tokens = await db.scalar(
        select(func.sum(AIDraft.completion_tokens))
    ) or 0

    # Estimated cost (gpt-4o-mini rates)
    cost_usd = (
        (total_prompt_tokens / 1_000_000) * 0.15
        + (total_completion_tokens / 1_000_000) * 0.60
    )

    acceptance_rate = (accepted / total_drafts * 100) if total_drafts > 0 else 0
    edit_rate = (accepted_with_edits / accepted * 100) if accepted > 0 else 0

    return {
        "total_drafts": total_drafts,
        "accepted": accepted,
        "accepted_with_edits": accepted_with_edits,
        "rejected": rejected,
        "pending_feedback": pending,
        "acceptance_rate_pct": round(acceptance_rate, 1),
        "edit_rate_pct": round(edit_rate, 1),
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "estimated_cost_usd": round(cost_usd, 4),
        "avg_tokens_per_draft": round(
            (total_prompt_tokens + total_completion_tokens) / max(total_drafts, 1)
        ),
    }
