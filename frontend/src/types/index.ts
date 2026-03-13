// ── Enums (must match backend exactly) ────────────────────────────────────────

export type TicketStatus = 'open' | 'pending' | 'in_progress' | 'resolved' | 'closed'
export type TicketPriority = 'low' | 'medium' | 'high' | 'urgent'
export type TicketCategory =
  | 'refund_request'
  | 'bug_report'
  | 'billing'
  | 'question'
  | 'feature_request'
  | 'account'
  | 'other'
export type MessageDirection = 'inbound' | 'outbound'
export type MessageSource = 'outlook' | 'platform'

// ── Core Models ────────────────────────────────────────────────────────────────

export interface Agent {
  id: string
  name: string
  email: string
}

export interface Message {
  id: string
  sender_email: string
  sender_name: string | null
  body_text: string
  body_html: string | null
  direction: MessageDirection
  source: MessageSource
  created_at: string
}

export interface Enrichment {
  sf_user_data: SFUserData | null
  sentry_events: SentryEvent[] | null
  posthog_recordings: PostHogRecording[] | null
  similar_tickets: SimilarTicket[] | null
  fetched_at: string
}

export interface SFUserData {
  id: string
  email: string
  plan: string
  created_at: string
  last_active: string | null
  refund_count: number
  stripe_customer_id: string | null
}

export interface SentryEvent {
  id: string
  title: string
  dateCreated: string
}

export interface PostHogRecording {
  id: string
  start_time: string
  duration: number
  url: string
}

export interface SimilarTicket {
  ticket_id: string
  score: number
  reason: string
}

export interface AIDraft {
  id: string
  draft_body: string
  confidence: number | null
  model_used: string
}

export interface Ticket {
  id: string
  display_id: string
  subject: string
  status: TicketStatus
  priority: TicketPriority
  category: TicketCategory | null
  sender_email: string
  sender_name: string | null
  detected_language: string | null
  tags: string[]
  assignee: Agent | null
  message_count: number
  created_at: string
  updated_at: string
  // Present only in detail view
  messages?: Message[]
  enrichment?: Enrichment
  ai_draft?: AIDraft
}

// ── WebSocket Events ───────────────────────────────────────────────────────────

export type WSEvent =
  | { event: 'new_message'; ticket_id: string; display_id: string; message_id: string }
  | { event: 'ticket_updated'; ticket_id: string; changes: Record<string, unknown> }
  | { event: 'pipeline_complete'; ticket_id: string; category: TicketCategory | null; priority: TicketPriority | null; language: string | null; requires_human_review: boolean; has_draft: boolean; assigned_agent_id: string | null }
  | { event: 'ai_draft_ready'; ticket_id: string; draft_preview: string }
  | { event: 'draft_regenerated'; ticket_id: string; draft_preview: string }

// ── API Response Shapes ────────────────────────────────────────────────────────

export interface TicketListResponse {
  tickets: Ticket[]
  total: number
}

export interface AIStats {
  total_drafts: number
  accepted: number
  accepted_with_edits: number
  rejected: number
  pending_feedback: number
  acceptance_rate_pct: number
  edit_rate_pct: number
  total_prompt_tokens: number
  total_completion_tokens: number
  estimated_cost_usd: number
  avg_tokens_per_draft: number
}
