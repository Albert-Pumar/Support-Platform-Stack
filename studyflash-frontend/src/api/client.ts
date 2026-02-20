/**
 * API Client
 * All HTTP calls to the FastAPI backend go through here.
 * Centralises error handling, base URL, and auth headers.
 */

import type {
  Ticket, TicketListResponse, TicketStatus,
  TicketPriority, TicketCategory, AIStats, Agent,
} from '../types'

const BASE = '/api/v1'

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`API ${res.status}: ${text}`)
  }
  // 202/204 responses have no body
  if (res.status === 202 || res.status === 204) return {} as T
  return res.json()
}

// ── Tickets ────────────────────────────────────────────────────────────────────

export const api = {
  tickets: {
    list(params?: {
      status?: TicketStatus
      category?: TicketCategory
      assignee_id?: string
      limit?: number
      offset?: number
    }): Promise<TicketListResponse> {
      const qs = new URLSearchParams()
      if (params?.status) qs.set('status', params.status)
      if (params?.category) qs.set('category', params.category)
      if (params?.assignee_id) qs.set('assignee_id', params.assignee_id)
      if (params?.limit) qs.set('limit', String(params.limit))
      if (params?.offset) qs.set('offset', String(params.offset))
      return request(`/tickets?${qs}`)
    },

    get(id: string): Promise<Ticket> {
      return request(`/tickets/${id}`)
    },

    update(id: string, body: {
      status?: TicketStatus
      priority?: TicketPriority
      assignee_id?: string | null
      category?: TicketCategory
      tags?: string[]
    }): Promise<{ ticket_id: string; updated: string[] }> {
      return request(`/tickets/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      })
    },

    reply(id: string, body: {
      body_html: string
      body_text: string
      agent_name: string
      agent_email: string
    }): Promise<{ message_id: string; ticket_id: string; status: string }> {
      return request(`/tickets/${id}/reply`, {
        method: 'POST',
        body: JSON.stringify(body),
      })
    },
  },

  // ── AI ───────────────────────────────────────────────────────────────────────

  ai: {
    regenerateDraft(ticketId: string, feedback?: string): Promise<{ status: string }> {
      return request(`/tickets/${ticketId}/ai/regenerate`, {
        method: 'POST',
        body: JSON.stringify({ feedback: feedback ?? null }),
      })
    },

    acceptDraft(ticketId: string, wasEdited: boolean): Promise<void> {
      return request(`/tickets/${ticketId}/ai/draft/accept`, {
        method: 'POST',
        body: JSON.stringify({ was_edited: wasEdited }),
      })
    },

    rejectDraft(ticketId: string): Promise<void> {
      return request(`/tickets/${ticketId}/ai/draft/reject`, {
        method: 'POST',
      })
    },

    reclassify(ticketId: string): Promise<{ status: string }> {
      return request(`/tickets/${ticketId}/ai/classify`, {
        method: 'POST',
      })
    },

    stats(): Promise<AIStats> {
      return request('/ai/stats')
    },
  },
}
