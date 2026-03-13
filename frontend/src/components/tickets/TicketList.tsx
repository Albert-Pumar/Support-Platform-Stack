import { useStore } from '../../store'
import { timeAgo, categoryLabel, statusColor, languageFlag, tagColor } from '../../utils/format'
import type { Ticket } from '../../types'

const CATEGORY_FILTERS = [
  { label: 'All', value: undefined },
  { label: '💸 Refund', value: 'refund_request' },
  { label: '🐛 Bug', value: 'bug_report' },
  { label: '❓ Question', value: 'question' },
  { label: '💳 Billing', value: 'billing' },
] as const

export function TicketList() {
  const tickets = useStore(s => s.tickets)
  const activeTicketId = useStore(s => s.activeTicketId)
  const isLoadingList = useStore(s => s.isLoadingList)
  const filters = useStore(s => s.filters)
  const selectTicket = useStore(s => s.selectTicket)
  const setFilter = useStore(s => s.setFilter)

  return (
    <div style={{ width: 360, flexShrink: 0, borderRight: '1px solid #ddd8f8', display: 'flex', flexDirection: 'column', overflow: 'hidden', background: '#fff' }}>

      {/* Search */}
      <div style={{ padding: '12px 16px', borderBottom: '1px solid #ddd8f8' }}>
        <div style={{ position: 'relative' }}>
          <span style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: '#7c6ea8', fontSize: 13 }}>🔍</span>
          <input
            value={filters.search}
            onChange={e => setFilter('search', e.target.value || undefined)}
            placeholder="Search tickets, users, IDs…"
            style={{
              width: '100%', background: '#f4f3ff', border: '1px solid #ddd8f8', borderRadius: 8,
              padding: '7px 12px 7px 32px', fontFamily: 'DM Mono, monospace', fontSize: 12,
              color: '#1a1340', outline: 'none',
            }}
          />
        </div>
      </div>

      {/* Category filters */}
      <div style={{ padding: '10px 16px', borderBottom: '1px solid #ddd8f8', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {CATEGORY_FILTERS.map(f => (
          <button
            key={f.label}
            onClick={() => setFilter('category', f.value)}
            style={{
              padding: '4px 10px', borderRadius: 20, fontSize: 11, fontWeight: 600,
              cursor: 'pointer', border: '1px solid',
              fontFamily: 'Syne, sans-serif',
              transition: 'all .15s',
              borderColor: filters.category === f.value || (!filters.category && !f.value) ? '#4f35d2' : '#ddd8f8',
              background: filters.category === f.value || (!filters.category && !f.value) ? '#ede9ff' : 'transparent',
              color: filters.category === f.value || (!filters.category && !f.value) ? '#4f35d2' : '#7c6ea8',
            }}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* List */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {isLoadingList && tickets.length === 0 ? (
          <Loading />
        ) : tickets.length === 0 ? (
          <Empty />
        ) : (
          tickets.map(ticket => (
            <TicketRow
              key={ticket.id}
              ticket={ticket}
              isSelected={ticket.id === activeTicketId}
              onClick={() => selectTicket(ticket.id)}
            />
          ))
        )}
      </div>
    </div>
  )
}

function TicketRow({ ticket, isSelected, onClick }: {
  ticket: Ticket; isSelected: boolean; onClick: () => void
}) {
  const isUnread = ticket.status === 'open' && !isSelected

  return (
    <div
      onClick={onClick}
      style={{
        padding: '14px 16px',
        borderBottom: '1px solid #ddd8f8',
        cursor: 'pointer',
        background: isSelected ? '#ede9ff' : '#fff',
        borderLeft: `3px solid ${isSelected ? '#4f35d2' : isUnread ? '#2563eb' : 'transparent'}`,
        transition: 'background .1s',
      }}
      onMouseEnter={e => { if (!isSelected) (e.currentTarget as HTMLElement).style.background = '#f4f3ff' }}
      onMouseLeave={e => { if (!isSelected) (e.currentTarget as HTMLElement).style.background = '#fff' }}
    >
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <div style={{ width: 7, height: 7, borderRadius: '50%', background: statusColor(ticket.status), flexShrink: 0 }} />
        <span style={{ fontFamily: 'DM Mono, monospace', fontSize: 10, color: '#7c6ea8' }}>{ticket.display_id}</span>
        {ticket.detected_language && (
          <span style={{ fontSize: 11 }}>{languageFlag(ticket.detected_language)}</span>
        )}
        <span style={{ marginLeft: 'auto', fontFamily: 'DM Mono, monospace', fontSize: 10, color: '#7c6ea8' }}>
          {timeAgo(ticket.updated_at)}
        </span>
      </div>

      {/* Sender */}
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 3, color: '#1a1340' }}>
        {ticket.sender_name || ticket.sender_email}
      </div>

      {/* Subject */}
      <div style={{ fontSize: 12, color: '#3d3068', marginBottom: 6, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
        {ticket.subject}
      </div>

      {/* Tags */}
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        {ticket.category && (
          <Tag label={categoryLabel(ticket.category)} />
        )}
        {ticket.tags?.slice(0, 2).map(tag => (
          <Tag key={tag} label={tag} colors={tagColor(tag)} />
        ))}
        {ticket.ai_draft && (
          <Tag label="✦ draft" colors={{ bg: 'rgba(37,99,235,.1)', color: '#2563eb' }} />
        )}
      </div>
    </div>
  )
}

function Tag({ label, colors }: { label: string; colors?: { bg: string; color: string } }) {
  return (
    <span style={{
      padding: '2px 7px', borderRadius: 4, fontSize: 10, fontWeight: 600,
      background: colors?.bg ?? 'rgba(79,53,210,.1)',
      color: colors?.color ?? '#4f35d2',
    }}>
      {label}
    </span>
  )
}

function Loading() {
  return (
    <div style={{ padding: 40, textAlign: 'center', color: '#7c6ea8', fontSize: 13 }}>
      Loading tickets…
    </div>
  )
}

function Empty() {
  return (
    <div style={{ padding: 40, textAlign: 'center', color: '#7c6ea8', fontSize: 13 }}>
      No tickets found
    </div>
  )
}
