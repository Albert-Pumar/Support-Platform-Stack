# Support — Frontend

React + TypeScript + Vite SPA for the internal support platform.

## Stack

- **React 18** + **TypeScript**
- **Zustand** — global state store (tickets, active ticket, WS events, notifications)
- **Vite** — dev server with API proxy to FastAPI backend
- **date-fns** — timestamp formatting
- No CSS framework — all styles are inline with CSS variables for consistency

## Architecture

```
src/
├── api/
│   └── client.ts          # All API calls (tickets, ai, agents)
├── components/
│   ├── layout/
│   │   ├── Sidebar.tsx    # Nav + WS status indicator
│   │   ├── StatsBar.tsx   # Live open/pending/refund counts
│   │   └── Notifications.tsx  # Auto-dismissing toast system
│   ├── tickets/
│   │   ├── TicketList.tsx # Filterable list with real-time updates
│   │   └── TicketDetail.tsx   # Thread + reply box + status actions
│   ├── ai/
│   │   └── AIDraftPanel.tsx   # Draft display, use/regenerate/feedback
│   └── enrichment/
│       └── EnrichmentPanel.tsx  # User data, Sentry, PostHog, similar tickets
├── hooks/
│   └── useWebSocket.ts    # Auto-reconnecting WS, feeds events to store
├── store/
│   └── index.ts           # Zustand store — single source of truth
├── types/
│   └── index.ts           # TypeScript types mirroring backend models
└── utils/
    └── format.ts          # timeAgo, labels, colors, language flags
```

## Key Data Flows

### Ticket Selection
```
User clicks ticket → store.selectTicket(id)
  → GET /api/v1/tickets/{id}   (full detail: messages + enrichment + ai_draft)
  → store.activeTicket updated
  → TicketDetail, EnrichmentPanel, AIDraftPanel all react
```

### Sending a Reply
```
Agent types in reply box → store.replyText updated
Agent clicks Send →
  1. POST /api/v1/tickets/{id}/reply  (sends via Graph API → Outlook)
  2. If draft was used: POST /api/v1/tickets/{id}/ai/draft/accept
     (records whether agent edited it — for quality tracking)
  3. Optimistic update: message added locally, status → 'pending'
  4. Toast notification: "Reply sent via Outlook ✓"
```

### AI Draft Flow
```
New ticket ingested →
  WebSocket event: 'pipeline_complete' { has_draft: true }
  → store reloads ticket detail
  → AIDraftPanel shows draft with confidence score

Agent clicks "Use Draft" →
  draft_body copied to reply textarea
  draftOriginalBody stored (to detect edits)

Agent clicks "Regenerate" →
  Optional feedback input appears ("make it shorter")
  POST /api/v1/tickets/{id}/ai/regenerate { feedback }
  → Backend queues Celery task
  → WebSocket event: 'draft_regenerated'
  → AIDraftPanel updates with new draft
```

### Real-time Updates (WebSocket)
```
useWebSocket hook connects to ws://localhost:8000/api/v1/tickets/ws
Auto-reconnects every 3s on disconnect

Events handled in store.handleWSEvent():
  new_message      → refresh list + reload detail if open
  pipeline_complete → update category/priority/language, reload if open, toast
  draft_regenerated → reload detail to show new draft
  ticket_updated   → refresh list
```

## Setup

```bash
cd frontend
npm install
npm run dev   # starts on http://localhost:5173

# API calls are proxied to http://localhost:8000 (vite.config.ts)
# Make sure the FastAPI backend is running first
```

## Production Build

```bash
npm run build
# Output: dist/
# Serve dist/ with nginx or any static file server
# Point /api/* to the FastAPI backend
```

## Environment

No `.env` needed — all API calls use relative URLs proxied through Vite in dev,
and through nginx/reverse proxy in production.
