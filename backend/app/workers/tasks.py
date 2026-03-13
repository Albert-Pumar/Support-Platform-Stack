"""
Celery Tasks
=============
Thin orchestration layer. Business logic lives in pipeline.py.

Task map:
  task_run_ai_pipeline     → full 4-stage pipeline (classify→similar→draft→assign)
  task_regenerate_draft    → reruns draft stage only (with optional agent feedback)
  task_enrich_ticket       → parallel data fetch from Sentry, PostHog, SF DB
  task_renew_graph_subscriptions → beat task, runs every 48h
"""

import asyncio
import sys

# Windows requires SelectorEventLoop for psycopg async compatibility.
# ProactorEventLoop (Windows default) does not support psycopg async mode.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uuid
from typing import Any

import structlog
from celery import Celery
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()

celery_app = Celery(
    "support_platform",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    beat_schedule={
        "renew-graph-subscriptions": {
            "task": "app.workers.tasks.task_renew_graph_subscriptions",
            "schedule": 60 * 60 * 48,
        },
    },
)


def _run(coro):
    """Run async coroutine from sync Celery task worker process."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)


# ── Full AI Pipeline ───────────────────────────────────────────────────────────

@celery_app.task(
    name="app.workers.tasks.task_run_ai_pipeline",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def task_run_ai_pipeline(self, ticket_id: str) -> dict[str, Any]:
    """Run the full AI pipeline: classify → similar → draft → assign."""
    log.info("task.pipeline.start", ticket_id=ticket_id)
    try:
        return _run(_run_pipeline_async(ticket_id))
    except Exception as exc:
        log.error("task.pipeline.failed", ticket_id=ticket_id, error=str(exc))
        raise self.retry(exc=exc)


async def _run_pipeline_async(ticket_id: str) -> dict[str, Any]:
    from datetime import datetime, timezone, timedelta
    from app.core.database import AsyncSessionLocal
    from app.models.models import Ticket, AIDraft, SupportAgent, TicketEnrichment
    from app.workers.pipeline import TicketContext, run_full_pipeline
    from app.services.ws_manager import ws_manager

    async with AsyncSessionLocal() as db:
        ticket = await db.scalar(
            select(Ticket)
            .where(Ticket.id == uuid.UUID(ticket_id))
            .options(
                selectinload(Ticket.messages),
                selectinload(Ticket.enrichment),
            )
        )
        if not ticket:
            log.warning("task.pipeline.ticket_not_found", ticket_id=ticket_id)
            return {"error": "ticket_not_found"}

        # First inbound message body
        inbound = [m for m in ticket.messages if m.direction == "inbound"]
        body = inbound[0].body_text if inbound else ticket.subject

        # Enrichment (may already be present if enrich task ran first)
        sf_data = ticket.enrichment.sf_user_data if ticket.enrichment else None
        sentry_events = ticket.enrichment.sentry_events if ticket.enrichment else None

        # Candidate tickets for similarity search (resolved, last 90 days)
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)
        candidates_result = await db.execute(
            select(Ticket)
            .where(Ticket.status == "resolved")
            .where(Ticket.created_at >= cutoff)
            .where(Ticket.id != ticket.id)
            .options(selectinload(Ticket.ai_draft))
            .limit(30)
            .order_by(Ticket.created_at.desc())
        )
        candidate_tickets = [
            {
                "id": str(t.id),
                "subject": t.subject,
                "summary_en": t.ai_draft.draft_body[:200] if t.ai_draft else "",
            }
            for t in candidates_result.scalars().all()
        ]

        # Available agents
        agents_result = await db.execute(
            select(SupportAgent).where(SupportAgent.is_active == True)
        )
        available_agents = [
            {"id": str(a.id), "name": a.name, "email": a.email}
            for a in agents_result.scalars().all()
        ]

        ctx = TicketContext(
            ticket_id=ticket_id,
            subject=ticket.subject,
            body=body,
            sf_user_data=sf_data,
            sentry_events=sentry_events,
            candidate_tickets=candidate_tickets,
            available_agents=available_agents,
        )

        results = await run_full_pipeline(ctx)

        # ── Persist ────────────────────────────────────────────────────────────
        if ctx.classification:
            ticket.detected_language = ctx.classification.language
            ticket.category = ctx.classification.category
            ticket.priority = ctx.classification.priority
            ticket.tags = ctx.classification.tags

        if results.get("assignment", {}).get("agent_id"):
            ticket.assignee_id = uuid.UUID(results["assignment"]["agent_id"])

        if "_draft_body" in results:
            meta = results.get("_draft_meta", {})
            existing = await db.scalar(
                select(AIDraft).where(AIDraft.ticket_id == uuid.UUID(ticket_id))
            )
            if existing:
                existing.draft_body = results["_draft_body"]
                existing.model_used = meta.get("model", settings.openai_model)
                existing.prompt_tokens = meta.get("prompt_tokens")
                existing.completion_tokens = meta.get("completion_tokens")
                existing.was_accepted = None
            else:
                db.add(AIDraft(
                    id=uuid.uuid4(),
                    ticket_id=uuid.UUID(ticket_id),
                    draft_body=results["_draft_body"],
                    confidence=results.get("classification", {}).get("confidence", 0.8),
                    model_used=meta.get("model", settings.openai_model),
                    prompt_tokens=meta.get("prompt_tokens"),
                    completion_tokens=meta.get("completion_tokens"),
                ))

        if results.get("similar_tickets") and not isinstance(results["similar_tickets"], dict):
            if ticket.enrichment:
                ticket.enrichment.similar_tickets = results["similar_tickets"]
            else:
                db.add(TicketEnrichment(
                    id=uuid.uuid4(),
                    ticket_id=uuid.UUID(ticket_id),
                    similar_tickets=results["similar_tickets"],
                ))

        await db.commit()

        # ── Notify frontend ────────────────────────────────────────────────────
        await ws_manager.broadcast_ticket_update(ticket_id, {
            "event": "pipeline_complete",
            "ticket_id": ticket_id,
            "category": ctx.classification.category if ctx.classification else None,
            "priority": ctx.classification.priority if ctx.classification else None,
            "language": ctx.classification.language if ctx.classification else None,
            "requires_human_review": ctx.classification.requires_human_review if ctx.classification else False,
            "has_draft": "_draft_body" in results,
            "assigned_agent_id": str(ticket.assignee_id) if ticket.assignee_id else None,
        })

        log.info(
            "task.pipeline.complete",
            ticket_id=ticket_id,
            total_cost_usd=results.get("total_cost_usd"),
        )
        return results


# ── Regenerate Draft ───────────────────────────────────────────────────────────

@celery_app.task(
    name="app.workers.tasks.task_regenerate_draft",
    bind=True,
    max_retries=2,
    default_retry_delay=10,
)
def task_regenerate_draft(self, ticket_id: str, feedback: str | None = None) -> dict[str, Any]:
    """
    Regenerate draft only. Called when agent clicks 'Regenerate' in the UI.
    Optional agent feedback (e.g. 'make it shorter') is appended to the prompt.
    """
    log.info("task.regen_draft.start", ticket_id=ticket_id)
    try:
        return _run(_regenerate_draft_async(ticket_id, feedback))
    except Exception as exc:
        raise self.retry(exc=exc)


async def _regenerate_draft_async(ticket_id: str, feedback: str | None) -> dict[str, Any]:
    from app.core.database import AsyncSessionLocal
    from app.models.models import Ticket, AIDraft
    from app.workers.pipeline import (
        TicketContext, ClassificationResult, generate_draft
    )
    from app.workers.llm_client import LLMClient
    from app.services.ws_manager import ws_manager

    async with AsyncSessionLocal() as db:
        ticket = await db.scalar(
            select(Ticket)
            .where(Ticket.id == uuid.UUID(ticket_id))
            .options(
                selectinload(Ticket.messages),
                selectinload(Ticket.enrichment),
                selectinload(Ticket.ai_draft),
            )
        )
        if not ticket:
            return {"error": "ticket_not_found"}

        inbound = [m for m in ticket.messages if m.direction == "inbound"]
        body = inbound[0].body_text if inbound else ticket.subject

        # Reconstruct classification from stored data
        classification = ClassificationResult(
            language=ticket.detected_language or "en",
            category=ticket.category or "other",
            priority=ticket.priority or "medium",
            priority_reason="",
            tags=ticket.tags or [],
            suggested_team="general",
            summary_en="",
            sentiment="neutral",
            confidence=0.9,
            requires_human_review=False,
        )

        ctx = TicketContext(
            ticket_id=ticket_id,
            subject=ticket.subject,
            body=body + (f"\n\n[Agent note: {feedback}]" if feedback else ""),
            sf_user_data=ticket.enrichment.sf_user_data if ticket.enrichment else None,
            sentry_events=ticket.enrichment.sentry_events if ticket.enrichment else None,
            classification=classification,
        )

        draft = await generate_draft(ctx, LLMClient())

        if ticket.ai_draft:
            ticket.ai_draft.draft_body = draft.body
            ticket.ai_draft.was_accepted = None
            ticket.ai_draft.was_edited = False
        else:
            db.add(AIDraft(
                id=uuid.uuid4(),
                ticket_id=uuid.UUID(ticket_id),
                draft_body=draft.body,
                confidence=0.8,
                model_used=draft.model,
                prompt_tokens=draft.prompt_tokens,
                completion_tokens=draft.completion_tokens,
            ))

        await db.commit()

        await ws_manager.broadcast_ticket_update(ticket_id, {
            "event": "draft_regenerated",
            "ticket_id": ticket_id,
            "draft_preview": draft.body[:100] + "...",
        })
        return {"regenerated": True, "length": len(draft.body)}


# ── Enrichment ─────────────────────────────────────────────────────────────────

@celery_app.task(
    name="app.workers.tasks.task_enrich_ticket",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def task_enrich_ticket(self, ticket_id: str) -> dict[str, Any]:
    """Fetch enrichment data from Sentry, PostHog, and DB in parallel."""
    log.info("task.enrich.start", ticket_id=ticket_id)
    try:
        return _run(_enrich_ticket_async(ticket_id))
    except Exception as exc:
        raise self.retry(exc=exc)


async def _enrich_ticket_async(ticket_id: str) -> dict[str, Any]:
    from app.core.database import AsyncSessionLocal
    from app.models.models import Ticket, TicketEnrichment

    async with AsyncSessionLocal() as db:
        ticket = await db.scalar(select(Ticket).where(Ticket.id == uuid.UUID(ticket_id)))
        if not ticket:
            return {}

        sf_data, sentry_data, posthog_data = await asyncio.gather(
            _fetch_sf_user_data(ticket.sender_email),
            _fetch_sentry_events(ticket.sender_email),
            _fetch_posthog_data(ticket.sender_email),
            return_exceptions=True,
        )

        existing = await db.scalar(
            select(TicketEnrichment).where(TicketEnrichment.ticket_id == uuid.UUID(ticket_id))
        )
        if existing:
            if not isinstance(sf_data, Exception): existing.sf_user_data = sf_data
            if not isinstance(sentry_data, Exception): existing.sentry_events = sentry_data
            if not isinstance(posthog_data, Exception): existing.posthog_recordings = posthog_data
        else:
            db.add(TicketEnrichment(
                id=uuid.uuid4(),
                ticket_id=uuid.UUID(ticket_id),
                sf_user_data=sf_data if not isinstance(sf_data, Exception) else None,
                sentry_events=sentry_data if not isinstance(sentry_data, Exception) else None,
                posthog_recordings=posthog_data if not isinstance(posthog_data, Exception) else None,
            ))

        await db.commit()
        log.info("task.enrich.complete", ticket_id=ticket_id)
        return {"enriched": True}


async def _fetch_sf_user_data(email: str) -> dict | None:
    if not settings.sf_database_url:
        return None
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text
    engine = create_async_engine(settings.sf_database_url)
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT u.id::text, u.email, u.created_at::text, u.plan,
                       u.stripe_customer_id,
                       COUNT(DISTINCT r.id) as refund_count,
                       MAX(s.last_active_at)::text as last_active
                FROM users u
                LEFT JOIN refunds r ON r.user_id = u.id
                LEFT JOIN sessions s ON s.user_id = u.id
                WHERE u.email = :email
                GROUP BY u.id, u.email, u.created_at, u.plan, u.stripe_customer_id
                LIMIT 1
            """),
            {"email": email},
        )
        row = result.mappings().first()
        return dict(row) if row else None


async def _fetch_sentry_events(email: str) -> list | None:
    if not settings.sentry_dsn:
        return None
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://sentry.io/api/0/projects/support_platform/support-app/events/",
            headers={"Authorization": f"Bearer {settings.sentry_dsn}"},
            params={"query": f"user.email:{email}", "limit": 5},
            timeout=10,
        )
        if resp.status_code == 200:
            return [
                {"id": e.get("id"), "title": e.get("title"), "dateCreated": e.get("dateCreated")}
                for e in resp.json().get("results", [])
            ]
    return None


async def _fetch_posthog_data(email: str) -> list | None:
    if not settings.posthog_api_key:
        return None
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{settings.posthog_host}/api/projects/@current/session_recordings/",
            headers={"Authorization": f"Bearer {settings.posthog_api_key}"},
            params={"email": email, "limit": 3},
            timeout=10,
        )
        if resp.status_code == 200:
            return [
                {
                    "id": r.get("id"),
                    "start_time": r.get("start_time"),
                    "duration": r.get("recording_duration"),
                    "url": f"{settings.posthog_host}/recordings/{r.get('id')}",
                }
                for r in resp.json().get("results", [])
            ]
    return None


# ── Subscription Renewal ───────────────────────────────────────────────────────

@celery_app.task(name="app.workers.tasks.task_renew_graph_subscriptions")
def task_renew_graph_subscriptions() -> None:
    log.info("task.renew_subscriptions.start")
    _run(_renew_subscriptions_async())


async def _renew_subscriptions_async() -> None:
    from datetime import datetime, timezone, timedelta
    from app.core.database import AsyncSessionLocal
    from app.models.models import GraphSubscription
    from app.services.graph_service import renew_webhook_subscription

    async with AsyncSessionLocal() as db:
        cutoff = datetime.now(timezone.utc) + timedelta(hours=24)
        result = await db.execute(
            select(GraphSubscription)
            .where(GraphSubscription.is_active == True)
            .where(GraphSubscription.expires_at <= cutoff)
        )
        for sub in result.scalars().all():
            try:
                data = await renew_webhook_subscription(sub.graph_subscription_id)
                sub.expires_at = datetime.fromisoformat(
                    data["expirationDateTime"].replace("Z", "+00:00")
                )
            except Exception as e:
                log.error("task.renew.failed", subscription_id=sub.graph_subscription_id, error=str(e))
        await db.commit()