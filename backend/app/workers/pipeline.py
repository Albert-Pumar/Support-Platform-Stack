"""
AI Pipeline
============
The full AI processing pipeline for a support ticket.
Each stage is a pure async function — no Celery, no DB sessions here.
Celery tasks in tasks.py call into this module.

Stages:
  1. classify()        → language, category, priority, tags, sentiment
  2. find_similar()    → semantically similar resolved tickets
  3. generate_draft()  → category-aware reply in the user's language
  4. auto_assign()     → suggest the right agent

Design principles:
  - Each function is independently testable
  - Prompt logic lives in prompts.py, not here
  - All context needed for a good response is passed as arguments (no hidden state)
  - Failures are logged and propagate — callers decide whether to retry
"""

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.workers.llm_client import LLMClient
from app.workers import prompts

log = structlog.get_logger(__name__)


# ── Data Classes ───────────────────────────────────────────────────────────────

@dataclass
class ClassificationResult:
    language: str                    # ISO 639-1
    category: str                    # TicketCategory enum value
    priority: str                    # TicketPriority enum value
    priority_reason: str
    tags: list[str]
    suggested_team: str              # "billing" | "technical" | "general"
    summary_en: str                  # English summary for agents who don't speak the language
    sentiment: str                   # "positive" | "neutral" | "frustrated" | "angry"
    confidence: float                # 0.0–1.0
    requires_human_review: bool      # True if edge case / urgent / low confidence
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""


@dataclass
class DraftResult:
    body: str                        # The draft reply text
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class AssignmentResult:
    agent_id: str | None             # UUID of suggested agent, or None
    reason: str
    confidence: float


@dataclass
class SimilarTicket:
    ticket_id: str
    relevance_score: float
    reason: str


@dataclass
class TicketContext:
    """All context needed to run the full pipeline for one ticket."""
    ticket_id: str
    subject: str
    body: str                        # Plain text body of the first message
    # Enrichment data (may be None if not yet fetched)
    sf_user_data: dict | None = None
    sentry_events: list | None = None
    # Prior classification (used for draft if classify() was already run)
    classification: ClassificationResult | None = None
    # Past resolved tickets for similarity search
    candidate_tickets: list[dict] = field(default_factory=list)
    # Available agents for assignment
    available_agents: list[dict] = field(default_factory=list)


# ── Stage 1: Classification ────────────────────────────────────────────────────

async def classify(ctx: TicketContext, llm: LLMClient) -> ClassificationResult:
    """
    Classify the ticket: detect language, category, priority, sentiment.
    Uses strict JSON mode with a well-structured prompt.
    Low temperature (0.1) for consistent, deterministic output.
    """
    log.info("pipeline.classify.start", ticket_id=ctx.ticket_id)

    user_prompt = prompts.CLASSIFY_USER_V1.format(
        subject=ctx.subject,
        body=ctx.body[:3000],  # Truncate long emails — first 3k chars is enough for classification
    )

    resp = await llm.complete(
        system=prompts.CLASSIFY_SYSTEM_V1,
        user=user_prompt,
        temperature=0.1,
        json_mode=True,
        task_name="classify",
        ticket_id=ctx.ticket_id,
    )

    data = resp.parsed
    _validate_classification(data)

    result = ClassificationResult(
        language=data.get("language", "en"),
        category=data.get("category", "other"),
        priority=data.get("priority", "medium"),
        priority_reason=data.get("priority_reason", ""),
        tags=data.get("tags", []),
        suggested_team=data.get("suggested_team", "general"),
        summary_en=data.get("summary_en", ""),
        sentiment=data.get("sentiment", "neutral"),
        confidence=float(data.get("confidence", 0.5)),
        requires_human_review=bool(data.get("requires_human_review", False)),
        prompt_tokens=resp.prompt_tokens,
        completion_tokens=resp.completion_tokens,
        cost_usd=resp.cost_usd,
        model=resp.model,
    )

    # Flag low-confidence results for human review regardless of model output
    if result.confidence < 0.6:
        result.requires_human_review = True
        log.warning(
            "pipeline.classify.low_confidence",
            ticket_id=ctx.ticket_id,
            confidence=result.confidence,
        )

    log.info(
        "pipeline.classify.complete",
        ticket_id=ctx.ticket_id,
        category=result.category,
        language=result.language,
        priority=result.priority,
        confidence=result.confidence,
    )
    return result


def _validate_classification(data: dict) -> None:
    """Raise if the LLM returned something structurally wrong."""
    valid_categories = {
        "refund_request", "bug_report", "billing", "question",
        "feature_request", "account", "other"
    }
    valid_priorities = {"low", "medium", "high", "urgent"}

    if data.get("category") not in valid_categories:
        log.warning("pipeline.classify.invalid_category", got=data.get("category"))
        data["category"] = "other"

    if data.get("priority") not in valid_priorities:
        log.warning("pipeline.classify.invalid_priority", got=data.get("priority"))
        data["priority"] = "medium"

    if not isinstance(data.get("tags"), list):
        data["tags"] = []

    # Clamp confidence to [0, 1]
    data["confidence"] = max(0.0, min(1.0, float(data.get("confidence", 0.5))))


# ── Stage 2: Similar Ticket Search ────────────────────────────────────────────

async def find_similar_tickets(
    ctx: TicketContext,
    llm: LLMClient,
) -> list[SimilarTicket]:
    """
    Find semantically similar resolved tickets for agent reference.

    Two-step approach:
    1. Pre-filter candidates by category (done in the caller via DB query)
    2. LLM ranks them by semantic relevance

    This is intentionally simple — no vector DB needed for MVP scale.
    At 1000+ resolved tickets, switch to pgvector embeddings.
    """
    if not ctx.candidate_tickets:
        return []

    log.info(
        "pipeline.similar.start",
        ticket_id=ctx.ticket_id,
        candidates=len(ctx.candidate_tickets),
    )

    candidates_json = json.dumps(
        [
            {
                "id": t["id"],
                "subject": t["subject"],
                "summary": t.get("summary_en", t["subject"])[:200],
                "resolution": t.get("resolution_note", "resolved"),
            }
            for t in ctx.candidate_tickets[:20]  # Max 20 candidates per LLM call
        ],
        ensure_ascii=False,
        indent=2,
    )

    user_prompt = prompts.SIMILAR_TICKETS_USER_V1.format(
        subject=ctx.subject,
        body_excerpt=ctx.body[:500],
        category=ctx.classification.category if ctx.classification else "unknown",
        candidates_json=candidates_json,
    )

    resp = await llm.complete(
        system=prompts.SIMILAR_TICKETS_SYSTEM_V1,
        user=user_prompt,
        temperature=0.1,
        json_mode=True,
        task_name="similar_tickets",
        ticket_id=ctx.ticket_id,
    )

    raw = resp.parsed
    if not isinstance(raw, list):
        raw = raw.get("tickets", []) if isinstance(raw, dict) else []

    results = [
        SimilarTicket(
            ticket_id=item["ticket_id"],
            relevance_score=float(item.get("relevance_score", 0)),
            reason=item.get("reason", ""),
        )
        for item in raw
        if item.get("relevance_score", 0) > 0.5
    ]

    log.info(
        "pipeline.similar.complete",
        ticket_id=ctx.ticket_id,
        matches=len(results),
    )
    return results


# ── Stage 3: Draft Generation ──────────────────────────────────────────────────

async def generate_draft(
    ctx: TicketContext,
    llm: LLMClient,
    similar_tickets: list[SimilarTicket] | None = None,
) -> DraftResult:
    """
    Generate a category-aware, language-correct draft reply.

    The system prompt is built dynamically:
    - Base system prompt (tone, format, sign-off rules)
    - Category-specific addon (refund rules, bug triage steps, etc.)

    The user prompt injects:
    - Full email body
    - Enriched user context (plan, refund history, last active)
    - References to similar resolved tickets
    """
    classification = ctx.classification
    if not classification:
        raise ValueError("classify() must be called before generate_draft()")

    log.info(
        "pipeline.draft.start",
        ticket_id=ctx.ticket_id,
        category=classification.category,
        language=classification.language,
    )

    # Build system prompt: base + category-specific rules
    category_addon = prompts.DRAFT_CATEGORY_ADDONS.get(classification.category, "")
    system_prompt = prompts.DRAFT_SYSTEM_BASE_V2 + category_addon

    # Build user context block from enrichment
    user_context = _format_user_context(ctx.sf_user_data, ctx.sentry_events)

    # Format similar tickets for reference
    similar_ref = _format_similar_tickets(similar_tickets or [])

    user_prompt = prompts.DRAFT_USER_V2.format(
        category=classification.category,
        language=classification.language,
        subject=ctx.subject,
        sentiment=classification.sentiment,
        body=ctx.body[:3000],
        user_context=user_context,
        similar_tickets=similar_ref,
    )

    resp = await llm.complete(
        system=system_prompt,
        user=user_prompt,
        temperature=0.4,  # More creative than classification, but still controlled
        json_mode=False,
        task_name="draft",
        ticket_id=ctx.ticket_id,
    )

    # Basic quality checks on the draft
    draft_body = resp.content.strip()
    draft_body = _post_process_draft(draft_body, classification.language)

    log.info(
        "pipeline.draft.complete",
        ticket_id=ctx.ticket_id,
        length=len(draft_body),
        cost_usd=round(resp.cost_usd, 6),
    )

    return DraftResult(
        body=draft_body,
        model=resp.model,
        prompt_tokens=resp.prompt_tokens,
        completion_tokens=resp.completion_tokens,
        cost_usd=resp.cost_usd,
    )


def _format_user_context(sf_data: dict | None, sentry_events: list | None) -> str:
    if not sf_data:
        return "No user data available."

    lines = [
        f"- Plan: {sf_data.get('plan', 'unknown')}",
        f"- Member since: {sf_data.get('created_at', 'unknown')}",
        f"- Last active: {sf_data.get('last_active', 'unknown')}",
        f"- Previous refunds issued: {sf_data.get('refund_count', 0)}",
    ]

    if sentry_events:
        lines.append(f"- Recent Sentry errors: {len(sentry_events)} error(s) in the last 30 days")
        # Include the most recent error type for context
        if sentry_events[0].get("title"):
            lines.append(f"  Most recent: {sentry_events[0]['title']}")

    return "\n".join(lines)


def _format_similar_tickets(similar: list[SimilarTicket]) -> str:
    if not similar:
        return "No similar past tickets found."

    lines = []
    for st in similar[:3]:
        lines.append(
            f"- Ticket {st.ticket_id} (relevance: {st.relevance_score:.0%}): {st.reason}"
        )
    return "\n".join(lines)


def _post_process_draft(draft: str, language: str) -> str:
    """
    Clean up common LLM draft issues:
    - Remove spurious subject line if model included one
    - Ensure sign-off is present
    - Strip markdown formatting (bold, italic) since we send plain text
    """
    import re

    # Strip any "Subject: ..." line at the start
    draft = re.sub(r"^(Subject|Betreff|Objet|Oggetto)\s*:.*\n", "", draft, flags=re.IGNORECASE)

    # Strip markdown bold/italic
    draft = re.sub(r"\*\*(.+?)\*\*", r"\1", draft)
    draft = re.sub(r"\*(.+?)\*", r"\1", draft)

    # Ensure sign-off exists
    sign_offs = ["support", "mit freundlichen", "freundliche grüsse",
                 "kind regards", "cordialement", "cordiali saluti"]
    has_signoff = any(s in draft.lower() for s in sign_offs)
    if not has_signoff:
        # Append appropriate sign-off based on language
        sign_off_map = {
            "de": "\n\nFreundliche Grüsse,\n Support Team",
            "fr": "\n\nCordialement,\nL'équipe Support",
            "it": "\n\nCordiali saluti,\nIl team di supporto",
            "en": "\n\nKind regards,\n Support Team",
        }
        draft += sign_off_map.get(language, "\n\nKind regards,\n Support Team")

    return draft.strip()


# ── Stage 4: Auto-Assignment ───────────────────────────────────────────────────

async def auto_assign(
    ctx: TicketContext,
    llm: LLMClient,
) -> AssignmentResult:
    """
    Suggest which agent should handle this ticket.

    For MVP: pure LLM-based matching using agent metadata.
    Future: factor in current workload from DB, language preferences, CSAT scores.

    Returns agent_id=None if no confident match — ticket stays unassigned
    and appears in the "Unassigned" queue.
    """
    if not ctx.available_agents:
        return AssignmentResult(agent_id=None, reason="No agents available", confidence=0.0)

    classification = ctx.classification
    if not classification:
        return AssignmentResult(agent_id=None, reason="Not yet classified", confidence=0.0)

    log.info("pipeline.assign.start", ticket_id=ctx.ticket_id)

    agents_json = json.dumps(ctx.available_agents, ensure_ascii=False, indent=2)

    user_prompt = prompts.ASSIGN_USER_V1.format(
        category=classification.category,
        priority=classification.priority,
        language=classification.language,
        summary=classification.summary_en,
        tags=", ".join(classification.tags),
        agents_json=agents_json,
    )

    resp = await llm.complete(
        system=prompts.ASSIGN_SYSTEM_V1,
        user=user_prompt,
        temperature=0.1,
        json_mode=True,
        task_name="assign",
        ticket_id=ctx.ticket_id,
    )

    data = resp.parsed
    agent_id = data.get("agent_id")
    confidence = float(data.get("confidence", 0.0))

    # Only assign if confidence is high enough
    if confidence < 0.65:
        agent_id = None
        log.info(
            "pipeline.assign.low_confidence",
            ticket_id=ctx.ticket_id,
            confidence=confidence,
        )

    result = AssignmentResult(
        agent_id=agent_id,
        reason=data.get("reason", ""),
        confidence=confidence,
    )

    log.info(
        "pipeline.assign.complete",
        ticket_id=ctx.ticket_id,
        agent_id=agent_id,
        confidence=confidence,
    )
    return result


# ── Full Pipeline Runner ───────────────────────────────────────────────────────

async def run_full_pipeline(ctx: TicketContext) -> dict[str, Any]:
    """
    Run all pipeline stages in the correct order for a new ticket.

    Stage order matters:
      1. classify    — must run first (other stages depend on its output)
      2. similar     — needs classification category for pre-filtering
      3. draft       — needs classification + similar tickets + enrichment
      4. assign      — needs classification

    Returns a summary dict for logging/storage.
    """
    llm = LLMClient()
    results: dict[str, Any] = {}

    # ── Stage 1: Classify ──────────────────────────────────────────────────────
    try:
        classification = await classify(ctx, llm)
        ctx.classification = classification
        results["classification"] = {
            "category": classification.category,
            "language": classification.language,
            "priority": classification.priority,
            "confidence": classification.confidence,
            "requires_human_review": classification.requires_human_review,
            "cost_usd": classification.cost_usd,
        }
    except Exception as e:
        log.error("pipeline.classify.error", ticket_id=ctx.ticket_id, error=str(e))
        results["classification"] = {"error": str(e)}
        # Cannot continue without classification
        return results

    # ── Stage 2: Similar Tickets ───────────────────────────────────────────────
    similar: list[SimilarTicket] = []
    try:
        similar = await find_similar_tickets(ctx, llm)
        results["similar_tickets"] = [
            {"ticket_id": s.ticket_id, "score": s.relevance_score, "reason": s.reason}
            for s in similar
        ]
    except Exception as e:
        log.error("pipeline.similar.error", ticket_id=ctx.ticket_id, error=str(e))
        results["similar_tickets"] = {"error": str(e)}
        # Non-fatal — continue with draft

    # ── Stage 3: Draft ─────────────────────────────────────────────────────────
    try:
        draft = await generate_draft(ctx, llm, similar_tickets=similar)
        results["draft"] = {
            "length": len(draft.body),
            "cost_usd": draft.cost_usd,
            "body_preview": draft.body[:100] + "...",
        }
        results["_draft_body"] = draft.body  # Full body for storage
        results["_draft_meta"] = {
            "model": draft.model,
            "prompt_tokens": draft.prompt_tokens,
            "completion_tokens": draft.completion_tokens,
        }
    except Exception as e:
        log.error("pipeline.draft.error", ticket_id=ctx.ticket_id, error=str(e))
        results["draft"] = {"error": str(e)}

    # ── Stage 4: Auto-Assignment ───────────────────────────────────────────────
    try:
        assignment = await auto_assign(ctx, llm)
        results["assignment"] = {
            "agent_id": assignment.agent_id,
            "reason": assignment.reason,
            "confidence": assignment.confidence,
        }
    except Exception as e:
        log.error("pipeline.assign.error", ticket_id=ctx.ticket_id, error=str(e))
        results["assignment"] = {"error": str(e)}

    # ── Total cost summary ─────────────────────────────────────────────────────
    total_cost = sum(
        v.get("cost_usd", 0)
        for v in results.values()
        if isinstance(v, dict) and "cost_usd" in v
    )
    results["total_cost_usd"] = round(total_cost, 6)

    log.info(
        "pipeline.complete",
        ticket_id=ctx.ticket_id,
        total_cost_usd=results["total_cost_usd"],
        stages_ok=[k for k, v in results.items() if isinstance(v, dict) and "error" not in v],
    )

    return results
