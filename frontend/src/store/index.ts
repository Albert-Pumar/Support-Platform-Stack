/**
 * Global Store (Zustand)
 * ========================
 * Single source of truth for the support platform UI.
 *
 * State slices:
 *   tickets        - list view data
 *   activeTicket   - full detail of the currently selected ticket
 *   notifications  - real-time toast notifications
 *   ws             - WebSocket connection status
 */

import { create } from 'zustand'
import { api } from '../api/client'
import type { Ticket, WSEvent, TicketStatus, TicketCategory } from '../types'

interface Notification {
  id: string
  type: 'info' | 'success' | 'warning' | 'ai'
  message: string
  ticketId?: string
}

interface Filters {
  status?: TicketStatus
  category?: TicketCategory
  search: string
}

interface StoreState {
  // ── Ticket List ─────────────────────────────────────────────────────────────
  tickets: Ticket[]
  allTickets: Ticket[]          // unfiltered — used for StatsBar counts
  totalTickets: number
  isLoadingList: boolean
  filters: Filters

  // ── Active Ticket ────────────────────────────────────────────────────────────
  activeTicketId: string | null
  activeTicket: Ticket | null
  isLoadingDetail: boolean
  isDraftPending: boolean   // Pipeline running, draft not yet ready

  // ── UI State ─────────────────────────────────────────────────────────────────
  replyText: string
  draftOriginalBody: string | null   // To detect if agent edited the draft
  notifications: Notification[]

  // ── WebSocket ────────────────────────────────────────────────────────────────
  wsConnected: boolean

  // ── Actions ──────────────────────────────────────────────────────────────────
  fetchTickets: () => Promise<void>
  selectTicket: (id: string) => Promise<void>
  updateTicketLocally: (id: string, changes: Partial<Ticket>) => void
  setReplyText: (text: string) => void
  setFilter: (key: keyof Filters, value: string | undefined) => void

  sendReply: (agentName: string, agentEmail: string) => Promise<void>
  useDraft: () => void
  regenerateDraft: (feedback?: string) => Promise<void>
  resolveTicket: () => Promise<void>
  reopenTicket: () => Promise<void>
  assignTicket: (agentId: string | null) => Promise<void>

  handleWSEvent: (event: WSEvent) => void
  setWsConnected: (v: boolean) => void
  addNotification: (n: Omit<Notification, 'id'>) => void
  dismissNotification: (id: string) => void
}

export const useStore = create<StoreState>((set, get) => ({
  tickets: [],
  allTickets: [] as Ticket[],   // unfiltered — used for StatsBar counts
  totalTickets: 0,
  isLoadingList: false,
  filters: { search: '' },

  activeTicketId: null,
  activeTicket: null,
  isLoadingDetail: false,
  isDraftPending: false,

  replyText: '',
  draftOriginalBody: null,
  notifications: [],
  wsConnected: false,

  // ── Fetch ticket list ────────────────────────────────────────────────────────

  fetchTickets: async () => {
    set({ isLoadingList: true })
    try {
      const { filters } = get()
      const data = await api.tickets.list({
        status: filters.status,
        category: filters.category,
        limit: 60,
      })
      // Client-side search filter (search is not a backend param for MVP)
      const search = filters.search.toLowerCase()
      const filtered = search
        ? data.tickets.filter(
            t =>
              t.subject.toLowerCase().includes(search) ||
              t.sender_email.toLowerCase().includes(search) ||
              (t.sender_name?.toLowerCase().includes(search) ?? false) ||
              t.display_id.toLowerCase().includes(search),
          )
        : data.tickets

      set({ tickets: filtered, totalTickets: data.total, isLoadingList: false })

      // Also keep an unfiltered copy for StatsBar counts — only refresh when
      // no filters are active so we don't overwrite with a subset
      const noFilters = !filters.status && !filters.category && !filters.search
      if (noFilters) {
        set({ allTickets: data.tickets })
      } else if (get().allTickets.length === 0) {
        // First load with filters already set — fetch unfiltered too
        const allData = await api.tickets.list({ limit: 200 })
        set({ allTickets: allData.tickets })
      }
    } catch (err) {
      console.error('fetchTickets failed', err)
      set({ isLoadingList: false })
    }
  },

  // ── Select and load a ticket ─────────────────────────────────────────────────

  selectTicket: async (id: string) => {
    if (get().activeTicketId === id) return
    set({ activeTicketId: id, activeTicket: null, isLoadingDetail: true, replyText: '' })
    try {
      const ticket = await api.tickets.get(id)
      set({
        activeTicket: ticket,
        isLoadingDetail: false,
        isDraftPending: !ticket.ai_draft && ticket.status === 'open',
        draftOriginalBody: ticket.ai_draft?.draft_body ?? null,
      })
    } catch (err) {
      console.error('selectTicket failed', err)
      set({ isLoadingDetail: false })
    }
  },

  updateTicketLocally: (id, changes) => {
    set(state => ({
      tickets: state.tickets.map(t => t.id === id ? { ...t, ...changes } : t),
      allTickets: state.allTickets.map(t => t.id === id ? { ...t, ...changes } : t),
      activeTicket: state.activeTicket?.id === id
        ? { ...state.activeTicket, ...changes }
        : state.activeTicket,
    }))
  },

  setReplyText: (text) => set({ replyText: text }),

  setFilter: (key, value) => {
    // When switching views, clear ALL filters first then set the new one.
    // This prevents stale category lingering when clicking nav items,
    // and stale status lingering when clicking category views.
    set({ filters: { search: get().filters.search, [key]: value } })
    get().fetchTickets()
  },

  // ── Send reply ───────────────────────────────────────────────────────────────

  sendReply: async (agentName, agentEmail) => {
    const { activeTicket, replyText, draftOriginalBody } = get()
    if (!activeTicket || !replyText.trim()) return

    const wasEdited = draftOriginalBody !== null && replyText !== draftOriginalBody
    const wasAIDraft = draftOriginalBody !== null

    try {
      await api.tickets.reply(activeTicket.id, {
        body_html: `<p>${replyText.replace(/\n/g, '<br>')}</p>`,
        body_text: replyText,
        agent_name: agentName,
        agent_email: agentEmail,
      })

      // Record AI draft feedback
      if (wasAIDraft) {
        await api.ai.acceptDraft(activeTicket.id, wasEdited).catch(() => {})
      }

      // Add the outbound message locally (optimistic)
      const newMsg = {
        id: crypto.randomUUID(),
        sender_email: agentEmail,
        sender_name: agentName,
        body_text: replyText,
        body_html: null,
        direction: 'outbound' as const,
        source: 'platform' as const,
        created_at: new Date().toISOString(),
      }

      set(state => ({
        replyText: '',
        draftOriginalBody: null,
        activeTicket: state.activeTicket ? {
          ...state.activeTicket,
          status: 'pending',
          messages: [...(state.activeTicket.messages ?? []), newMsg],
        } : null,
      }))

      get().updateTicketLocally(activeTicket.id, { status: 'pending' })
      get().addNotification({ type: 'success', message: 'Reply sent via Outlook ✓' })
    } catch (err) {
      console.error('sendReply failed', err)
      get().addNotification({ type: 'warning', message: 'Failed to send reply — try again' })
    }
  },

  // ── Use AI draft ─────────────────────────────────────────────────────────────

  useDraft: () => {
    const draft = get().activeTicket?.ai_draft
    if (!draft) return
    set({ replyText: draft.draft_body, draftOriginalBody: draft.draft_body })
  },

  // ── Regenerate draft ─────────────────────────────────────────────────────────

  regenerateDraft: async (feedback?: string) => {
    const { activeTicket } = get()
    if (!activeTicket) return
    set({ isDraftPending: true })
    try {
      await api.ai.regenerateDraft(activeTicket.id, feedback)
      get().addNotification({ type: 'ai', message: '✦ Regenerating draft…', ticketId: activeTicket.id })
    } catch (err) {
      set({ isDraftPending: false })
    }
  },

  // ── Status actions ────────────────────────────────────────────────────────────

  resolveTicket: async () => {
    const { activeTicket } = get()
    if (!activeTicket) return
    await api.tickets.update(activeTicket.id, { status: 'resolved' })
    get().updateTicketLocally(activeTicket.id, { status: 'resolved' })
    get().addNotification({ type: 'success', message: `${activeTicket.display_id} resolved ✓` })
  },

  reopenTicket: async () => {
    const { activeTicket } = get()
    if (!activeTicket) return
    await api.tickets.update(activeTicket.id, { status: 'open' })
    get().updateTicketLocally(activeTicket.id, { status: 'open' })
  },

  assignTicket: async (agentId) => {
    const { activeTicket } = get()
    if (!activeTicket) return
    await api.tickets.update(activeTicket.id, { assignee_id: agentId })
    get().fetchTickets()
    // activeTicket assignee will update via fetchTickets or next reload
  },

  // ── WebSocket event handler ───────────────────────────────────────────────────

  handleWSEvent: (event: WSEvent) => {
    const { activeTicketId } = get()

    switch (event.event) {
      case 'new_message': {
        // Refresh list to update message count + updated_at ordering
        get().fetchTickets()
        // If this is the open ticket, reload its detail
        if (event.ticket_id === activeTicketId) {
          api.tickets.get(event.ticket_id).then(ticket =>
            set({ activeTicket: ticket })
          )
        }
        get().addNotification({
          type: 'info',
          message: `New message on ${event.display_id}`,
          ticketId: event.ticket_id,
        })
        break
      }

      case 'pipeline_complete': {
        // Update the ticket in list + detail with new classification data
        get().updateTicketLocally(event.ticket_id, {
          category: event.category ?? undefined,
          priority: event.priority ?? undefined,
          detected_language: event.language ?? undefined,
        })
        if (event.ticket_id === activeTicketId) {
          set({ isDraftPending: !event.has_draft })
          // Reload to get the full draft + assignment
          api.tickets.get(event.ticket_id).then(ticket =>
            set({
              activeTicket: ticket,
              isDraftPending: false,
              draftOriginalBody: ticket.ai_draft?.draft_body ?? null,
            })
          )
        }
        if (event.has_draft) {
          get().addNotification({
            type: 'ai',
            message: `✦ AI draft ready`,
            ticketId: event.ticket_id,
          })
        }
        break
      }

      case 'draft_regenerated': {
        if (event.ticket_id === activeTicketId) {
          api.tickets.get(event.ticket_id).then(ticket =>
            set({
              activeTicket: ticket,
              isDraftPending: false,
              draftOriginalBody: ticket.ai_draft?.draft_body ?? null,
            })
          )
        }
        break
      }

      case 'ticket_updated': {
        get().fetchTickets()
        break
      }
    }
  },

  setWsConnected: (v) => set({ wsConnected: v }),

  addNotification: (n) => {
    const id = crypto.randomUUID()
    set(state => ({ notifications: [...state.notifications, { ...n, id }] }))
    // Auto-dismiss after 4 seconds
    setTimeout(() => get().dismissNotification(id), 4000)
  },

  dismissNotification: (id) =>
    set(state => ({ notifications: state.notifications.filter(n => n.id !== id) })),
}))