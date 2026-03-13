"""
Graph API Webhook Router
=========================
Handles the two types of requests Graph API makes to our endpoint:

1. VALIDATION (GET): When we register a subscription, Graph API sends a GET
   with a validationToken query param. We must echo it back within 10 seconds
   or the subscription is rejected.

2. NOTIFICATIONS (POST): When a new email arrives, Graph API POSTs a batch
   of notification objects. We validate the clientState, then process each
   notification asynchronously (respond fast, process in background).

Microsoft docs:
https://learn.microsoft.com/en-us/graph/webhooks
"""

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.graph_service import (
    fetch_message,
    parse_graph_message,
    validate_webhook_notification,
)
from app.services.ingestion_service import ingest_email

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhook"])


# ── Subscription Validation ────────────────────────────────────────────────────

@router.get("/graph")
async def validate_graph_subscription(
    validationToken: str = Query(..., description="Token sent by Graph API to validate the endpoint"),
):
    """
    Graph API subscription validation handshake.

    Graph sends this GET request when we create/renew a subscription.
    We MUST respond with the validationToken as plain text within 10 seconds.
    FastAPI will handle the rest.
    """
    log.info("graph.webhook.validation", token_preview=validationToken[:20])
    return Response(content=validationToken, media_type="text/plain")


# ── Notification Handler ───────────────────────────────────────────────────────

@router.post("/graph", status_code=202)
async def handle_graph_notification(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Receive email notification batches from Graph API.

    Critical design decisions:
    - Always return 202 Accepted quickly (within 30s or Graph retries)
    - Do the heavy work (fetching message content, DB writes) in background
    - Validate clientState on every notification to prevent spoofing
    - Handle batches: Graph can send multiple notifications in one POST
    """
    body = await request.json()
    notifications = body.get("value", [])

    log.info("graph.webhook.received", notification_count=len(notifications))

    for notification in notifications:
        # ── Security: validate clientState ────────────────────────────────────
        client_state = notification.get("clientState", "")
        if not validate_webhook_notification(client_state):
            log.warning(
                "graph.webhook.invalid_client_state",
                received=client_state[:20],
            )
            continue  # Skip this notification, don't process untrusted data

        change_type = notification.get("changeType")
        resource_data = notification.get("resourceData", {})
        message_id = resource_data.get("id")

        if change_type != "created" or not message_id:
            log.debug("graph.webhook.skipped", change_type=change_type)
            continue

        log.info("graph.webhook.processing", message_id=message_id)

        # ── Queue background processing ────────────────────────────────────────
        # We schedule the actual work as a background task so we can return
        # 202 to Graph API immediately. If we take >30s, Graph will retry.
        background_tasks.add_task(
            _process_notification,
            message_id=message_id,
            subscription_id=notification.get("subscriptionId"),
        )

    # 202 Accepted — Graph API requires this to confirm receipt
    return {"received": len(notifications)}


# ── Background Processing ──────────────────────────────────────────────────────

async def _process_notification(message_id: str, subscription_id: str | None) -> None:
    """
    Background task: fetch the full email from Graph API and run ingestion.

    This runs after we've already returned 202 to Graph API, so we have
    time to do the DB work properly.
    """
    from app.core.database import AsyncSessionLocal

    log.info("graph.notification.processing", message_id=message_id)

    try:
        # Fetch the full message content from Graph API
        raw_message = await fetch_message(message_id)
        parsed = parse_graph_message(raw_message)

        # Run the ingestion pipeline
        async with AsyncSessionLocal() as db:
            ticket = await ingest_email(parsed, db)
            await db.commit()

            if ticket:
                log.info(
                    "graph.notification.processed",
                    ticket_id=str(ticket.id),
                    display_id=ticket.display_id,
                )
            else:
                log.info("graph.notification.skipped_duplicate", message_id=message_id)

    except Exception as e:
        log.error(
            "graph.notification.failed",
            message_id=message_id,
            error=str(e),
            exc_info=True,
        )
        # In production: send to dead-letter queue or Sentry
        raise
