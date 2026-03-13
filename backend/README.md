# Support Platform — Backend

FastAPI backend for the internal support ticketing platform with full Microsoft Outlook parity.

## Architecture Overview

```
Outlook Inbox
     │
     │  (new email arrives)
     ▼
Microsoft Graph API
     │
     │  POST /api/v1/webhook/graph
     ▼
FastAPI Webhook Endpoint
     │
     ├── Validate clientState (security)
     ├── Return 202 immediately
     └── BackgroundTask: fetch full message from Graph API
              │
              ▼
        Ingestion Service
              │
              ├── Deduplication check (outlook_message_id)
              ├── New ticket OR reply to existing thread?
              ├── Create Ticket + Message in Postgres
              └── Dispatch Celery tasks (non-blocking)
                       │
                       ├── task_classify_ticket
                       │        └── GPT-4o: language, category, priority, tags
                       │                 └── task_generate_ai_draft
                       │                          └── GPT-4o: draft reply in user's language
                       │
                       └── task_enrich_ticket (parallel)
                                ├── Postgres: user data, plan, refund history
                                ├── Sentry API: recent errors for this user
                                └── PostHog API: session recordings

WebSocket → Frontend notified of all updates in real-time
```

## Outlook Parity — How It Works

The `conversationId` from Graph API is the key to keeping both worlds in sync:

```
INBOUND (Outlook → Platform):
  User sends email → Graph API webhook fires → we create ticket
  User replies in Outlook → Graph API webhook fires → we add message to thread

OUTBOUND (Platform → Outlook):
  Agent replies in platform → POST /api/v1/tickets/{id}/reply
  → We call Graph API /messages/{id}/reply
  → Reply appears in Outlook thread natively
  → Other Outlook users see it in Sent Items
  → We record it in our DB (direction=outbound, source=platform)
```

## Local Development Setup

### Prerequisites
- Docker & Docker Compose
- ngrok (for Graph API webhooks in local dev)
- Azure AD app registration with Mail.ReadWrite + Mail.Send permissions

### 1. Clone and configure

```bash
cp .env.example .env
# Fill in your Azure credentials, OpenAI key, etc.
```

### 2. Start infrastructure

```bash
docker-compose up postgres redis -d
```

### 3. Run migrations

```bash
pip install -r requirements.txt
alembic upgrade head
```

### 4. Start ngrok (Graph API needs a public HTTPS URL)

```bash
ngrok http 8000
# Copy the https URL → set WEBHOOK_BASE_URL in .env
```

### 5. Start the API

```bash
uvicorn app.main:app --reload --port 8000
```

On startup, the app automatically registers the Graph API webhook subscription.

### 6. Start Celery worker

```bash
celery -A app.workers.tasks.celery_app worker --loglevel=info
```

### 7. (Optional) Start Celery beat for scheduled renewal

```bash
celery -A app.workers.tasks.celery_app beat --loglevel=info
```

### Or: run everything with Docker

```bash
docker-compose up --build
```

## Azure AD Setup

1. Go to [portal.azure.com](https://portal.azure.com) → Azure Active Directory → App Registrations → New registration
2. **API Permissions** (Application permissions, not delegated):
   - `Mail.Read`
   - `Mail.ReadWrite`
   - `Mail.Send`
   - Grant admin consent ✓
3. **Certificates & Secrets** → New client secret → copy to `.env`
4. Copy **Application (client) ID** and **Directory (tenant) ID** to `.env`

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/webhook/graph` | Graph API subscription validation |
| `POST` | `/api/v1/webhook/graph` | Receive email notifications |
| `GET` | `/api/v1/tickets` | List all tickets (filterable) |
| `GET` | `/api/v1/tickets/{id}` | Get ticket with full thread |
| `POST` | `/api/v1/tickets/{id}/reply` | Send reply (via Graph API + saved to DB) |
| `PATCH` | `/api/v1/tickets/{id}` | Update status, assignee, priority |
| `WS` | `/api/v1/tickets/ws` | Global real-time updates |
| `WS` | `/api/v1/tickets/{id}/ws` | Per-ticket real-time updates |
| `GET` | `/health` | Health check |

## Key Design Decisions

### Why not IMAP?
Graph API gives us webhook push (vs polling), proper conversation threading, and bidirectional send that maintains the Outlook thread natively. IMAP would require polling and can't send replies into an existing thread cleanly.

### Why Celery for AI tasks?
Webhook handlers must respond to Graph API within 30 seconds. AI classification + enrichment can take 5-15s per source. Celery lets us respond immediately and process asynchronously.

### Idempotent ingestion
Every message is keyed by `outlook_message_id`. Graph API can send duplicate notifications — we silently skip duplicates.

### Subscription renewal
Graph API webhook subscriptions for mail resources expire after 3 days. A Celery beat task runs every 48 hours to renew them before expiry.
