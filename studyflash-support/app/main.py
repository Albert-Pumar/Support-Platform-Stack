"""
Studyflash Support Platform — FastAPI Application
"""

import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import engine, Base
from app.routers import webhook, tickets, ai

log = structlog.get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: create DB tables + register Graph API webhook subscription.
    Shutdown: clean up.
    """
    log.info("app.startup", env=settings.app_env)

    # Create all tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("app.db.tables_ready")

    # Register Graph API webhook subscription on startup
    if settings.azure_client_id and settings.azure_tenant_id:
        try:
            from app.services.graph_service import create_webhook_subscription
            from app.models.models import GraphSubscription
            from app.core.database import AsyncSessionLocal
            from datetime import datetime, timezone
            import uuid

            sub_data = await create_webhook_subscription()

            async with AsyncSessionLocal() as db:
                sub = GraphSubscription(
                    id=uuid.uuid4(),
                    graph_subscription_id=sub_data["id"],
                    resource=sub_data["resource"],
                    change_types=sub_data["changeType"],
                    expires_at=datetime.fromisoformat(
                        sub_data["expirationDateTime"].replace("Z", "+00:00")
                    ),
                )
                db.add(sub)
                await db.commit()

            log.info("app.graph_webhook.registered", subscription_id=sub_data["id"])
        except Exception as e:
            # Don't crash the app if Graph registration fails (e.g. in local dev)
            log.warning("app.graph_webhook.registration_failed", error=str(e))
    else:
        log.info("app.graph_webhook.skipped", reason="Azure credentials not configured")

    yield

    log.info("app.shutdown")


app = FastAPI(
    title="Studyflash Support Platform",
    version="0.1.0",
    description="Internal support ticketing platform with Outlook parity",
    lifespan=lifespan,
)

# ── CORS ───────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(webhook.router, prefix="/api/v1")
app.include_router(tickets.router, prefix="/api/v1")
app.include_router(ai.router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.app_env}
