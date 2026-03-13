# Support Platform

An internal AI-powered support platform built to replace a fragmented workflow where agents juggled Outlook, Sentry, and the production database across separate tabs to answer every ticket.

The platform centralises the full support loop: emails arrive from Outlook, an AI pipeline classifies them, pulls context from three data sources, and drafts a reply in the customer's language, all before the agent opens the ticket. The agent reviews, edits if needed, and sends. The reply lands in the customer's original Outlook thread.

---

## What it does

**For the agent**
- Every incoming email becomes a ticket with category, priority, and language already detected
- A draft reply is waiting when they open it — written in the customer's language, with context already looked up
- Sending a reply from the platform delivers it as a real email in the original Outlook thread (no copy, no forward)
- The dashboard updates in real time when new tickets arrive or pipelines complete (no refreshing)

**For the business**
- Full enrichment per ticket: user plan, billing history, recent Sentry errors, PostHog session recordings, and similar past tickets (all in one panel)
- AI draft confidence score so agents know when to trust the draft and when to rewrite
- Ticket classification into categories (refund request, bug report, account issue, question) with priority scoring

---

## Architecture

Three layers working together:

```
EXTERNAL          BACKEND                        FRONTEND
─────────         ───────────────────────────    ────────────────────────
Outlook     →     webhook.py                     useWebSocket.ts
Mailbox           ingestion_service.py      →    Zustand store
                  Redis queue                    AIDraftPanel
                  Celery worker                  EnrichmentPanel
                  ├─ Classify (LLM)              TicketDetail
                  ├─ Enrich (SF DB, Sentry,      TicketList
                  │  PostHog)                    Sidebar + StatsBar
                  ├─ Draft (Groq)
                  └─ Assign (LLM)
                  PostgreSQL
                  ws_manager.py             →    (real-time push)
```

**Inbound flow:** Outlook sends a webhook notification → `webhook.py` validates and acknowledges immediately → `ingestion_service.py` deduplicates and creates the ticket → a Celery task runs the 4-stage AI pipeline → `ws_manager.py` pushes a WebSocket event to the frontend → the draft appears on the agent's screen.

**Reply flow:** Agent writes or edits the draft → `POST /api/v1/tickets/{id}/reply` → `graph_service.py` sends via Microsoft Graph API → reply appears in the customer's original Outlook thread → ticket status updates live across all connected sessions.

---

## Tech stack

| Layer | Technology | Why |
|---|---|---|
| Backend | FastAPI + Python 3.10 | Async-first, native WebSocket, auto-generated API docs |
| Task queue | Celery + Redis | AI pipeline runs async, webhook responds in <100ms |
| Database | PostgreSQL + SQLAlchemy async | Reliable, relational, pgvector-ready for future similarity search |
| AI | Groq — llama-3.3-70b-versatile | Free tier, OpenAI-compatible API, swap with zero code change |
| Email | Microsoft Graph API | Webhook push (no polling), native Outlook thread parity |
| Frontend | React + TypeScript + Vite | Fast build, full type safety across API boundary |
| State | Zustand | 350 lines vs Redux's 1000+, no full-tree re-renders |
| Real-time | WebSocket (FastAPI native) | Server pushes updates, no polling latency |

---

## Project structure

```
platform/
├── backend/          # Backend (FastAPI)
│   ├── app/
│   │   ├── core/                # Config, database connection
│   │   ├── models/              # SQLAlchemy models (6 tables)
│   │   ├── routers/             # webhook.py, tickets.py, ai.py
│   │   ├── services/            # graph_service, ingestion, ws_manager
│   │   └── workers/             # Celery tasks, pipeline, LLM client, prompts
│   ├── alembic/                 # Database migrations
│   ├── docker-compose.yml
│   ├── requirements.txt
│   └── .env.example
│
├── frontend/         # Frontend (React + TypeScript)
│   └── src/
│       ├── components/
│       │   ├── ai/              # AIDraftPanel
│       │   ├── enrichment/      # EnrichmentPanel
│       │   ├── layout/          # Sidebar, StatsBar, Notifications
│       │   └── tickets/         # TicketList, TicketDetail
│       ├── store/               # Zustand global state
│       ├── api/                 # Typed HTTP client
│       ├── hooks/               # useWebSocket
│       └── types/               # TypeScript types
│
├── architecture-diagram.html    # Interactive system diagram
├── seed_demo.py                 # Seeds DB with demo tickets + enrichment
└── README.md
```

---

## Running locally

### Prerequisites
- Docker Desktop
- Python 3.10+
- Node.js 18+
- A [Groq API key](https://console.groq.com) (free)
- ngrok (only needed for live Outlook integration)

### 1. Start infrastructure

```bash
cd backend
docker-compose up postgres redis -d
```

### 2. Configure environment

```bash
cp .env.example .env
# Fill in DATABASE_URL, OPENAI_API_KEY (your Groq key), and REDIS_URL
# Everything else is optional for local demo
```

### 3. Install and migrate

```bash
pip install -r requirements.txt
alembic upgrade head
```

### 4. Start the backend

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. Start the Celery worker

```bash
# Windows
celery -A app.workers.tasks.celery_app worker --loglevel=info --pool=solo

# Mac / Linux
celery -A app.workers.tasks.celery_app worker --loglevel=info
```

### 6. Seed demo tickets

```bash
python seed_demo.py
```

This creates 6 tickets in German, Dutch, and Italian with full enrichment data and pre-generated AI drafts (no Outlook connection required to see the full UI).

### 7. Start the frontend

```bash
cd ../frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

---

## Demo mode vs live mode

The platform works in two modes:

**Demo mode** (no Azure setup needed) — run `seed_demo.py` to populate tickets directly into the database. The full UI works including AI drafts, enrichment panels, and ticket management. Replies won't send real emails.

**Live mode** — requires an Azure App Registration with `Mail.Read`, `Mail.ReadWrite`, and `Mail.Send` permissions, plus ngrok for the webhook URL in local development. Full setup instructions in [`backend/README.md`](backend/README.md).

---

## Key design decisions

**Why not just use a helpdesk SaaS?** The goal was native Outlook thread parity, replies needed to land in the customer's original inbox thread, not arrive as a separate email from a third-party domain. This required building directly on the Graph API.

**Why Celery instead of FastAPI background tasks?** Background tasks run inside the web server process. If the server restarts mid-pipeline, the task is lost. Celery tasks survive restarts because they sit in Redis waiting to be picked up.

**Why Groq instead of GPT-4o?** The API is fully OpenAI-compatible, switching is a single environment variable change. Groq's free tier made it practical for development and demonstration without cost.

**Why Zustand instead of Redux?** The entire state layer is ~350 lines. Redux would require action creators, reducers, selectors, and middleware for the same functionality. The simplicity made the codebase easier to reason about and extend.

---

## What's next

- Authentication (JWT + role-based access for agents vs admins)
- pgvector for semantic similarity search across historical tickets
- Bulk actions (resolve multiple tickets, reassign queue)
- Mobile-responsive layout
- Fine-tuning the draft model on accepted/rejected draft history

---

Copyright (c) 2026 Albert Pumar

All rights reserved. This code and its contents may not be used,
copied, modified, distributed, or submitted as part of any product
or service without the express written permission of the copyright holder.
