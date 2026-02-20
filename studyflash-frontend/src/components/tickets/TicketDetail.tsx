import { useState, useRef, useEffect } from 'react'
import { useStore } from '../../store'
import { timeAgo, statusLabel, statusColor, languageFlag } from '../../utils/format'
import { AIDraftPanel } from '../ai/AIDraftPanel'
import type { Message } from '../../types'

// Hardcoded current agent — in prod, comes from auth context
const CURRENT_AGENT = { name: 'Albert Pumar', email: 'albertpumar@studyflash.ch' }

export function TicketDetail() {
  const activeTicket = useStore(s => s.activeTicket)
  const isLoadingDetail = useStore(s => s.isLoadingDetail)
  const replyText = useStore(s => s.replyText)
  const setReplyText = useStore(s => s.setReplyText)
  const sendReply = useStore(s => s.sendReply)
  const resolveTicket = useStore(s => s.resolveTicket)
  const reopenTicket = useStore(s => s.reopenTicket)

  const [isSending, setIsSending] = useState(false)
  const threadRef = useRef<HTMLDivElement>(null)

  // Scroll to bottom when messages change
  useEffect(() => {
    if (threadRef.current) {
      threadRef.current.scrollTop = threadRef.current.scrollHeight
    }
  }, [activeTicket?.messages?.length])

  if (!activeTicket && !isLoadingDetail) {
    return <EmptyState />
  }

  if (isLoadingDetail || !activeTicket) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#7c6ea8' }}>
        Loading ticket…
      </div>
    )
  }

  const isResolved = activeTicket.status === 'resolved'

  async function handleSend() {
    if (!replyText.trim() || isSending) return
    setIsSending(true)
    await sendReply(CURRENT_AGENT.name, CURRENT_AGENT.email)
    setIsSending(false)
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

      {/* Header */}
      <div style={{ padding: '16px 24px', borderBottom: '1px solid #ddd8f8', background: '#fff', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 12 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontFamily: 'DM Mono, monospace', fontSize: 11, color: '#7c6ea8', marginBottom: 4 }}>
              {activeTicket.display_id} · via Outlook · {timeAgo(activeTicket.created_at)}
            </div>
            <h1 style={{ fontSize: 17, fontWeight: 700, lineHeight: 1.3, color: '#1a1340', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {activeTicket.subject}
            </h1>
          </div>

          {/* Actions */}
          <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
            {isResolved ? (
              <ActionButton onClick={reopenTicket} label="↩ Reopen" />
            ) : (
              <ActionButton onClick={resolveTicket} label="✓ Resolve" primary={false} />
            )}
          </div>
        </div>

        {/* Meta row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
          <MetaChip icon="👤" value={activeTicket.sender_name || activeTicket.sender_email} />
          <MetaChip icon="📧" value={activeTicket.sender_email} mono />
          {activeTicket.detected_language && (
            <MetaChip icon={languageFlag(activeTicket.detected_language)} value={activeTicket.detected_language.toUpperCase()} />
          )}

          {/* Status */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6,
            background: '#f4f3ff', border: '1px solid #ddd8f8',
            borderRadius: 20, padding: '3px 10px',
            fontSize: 11, fontWeight: 600,
            color: statusColor(activeTicket.status),
          }}>
            <div style={{ width: 6, height: 6, borderRadius: '50%', background: statusColor(activeTicket.status) }} />
            {statusLabel(activeTicket.status)}
          </div>

          {/* Assignee */}
          <AssigneeButton ticket={activeTicket} />
        </div>
      </div>

      {/* Thread */}
      <div ref={threadRef} style={{ flex: 1, overflowY: 'auto', padding: 24, display: 'flex', flexDirection: 'column', gap: 20, background: '#f4f3ff' }}>
        {(activeTicket.messages ?? []).map(msg => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
      </div>

      {/* AI Draft */}
      {!isResolved && <AIDraftPanel />}

      {/* Reply box */}
      {!isResolved && (
        <div style={{ padding: '16px 24px', borderTop: '1px solid #ddd8f8', background: '#fff', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <span style={{ fontSize: 11, color: '#7c6ea8', fontWeight: 700, letterSpacing: '.05em', textTransform: 'uppercase' }}>Replying as:</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: '#f4f3ff', border: '1px solid #ddd8f8', borderRadius: 20, padding: '3px 10px 3px 6px', fontSize: 11, fontWeight: 600 }}>
              <div style={{ width: 18, height: 18, borderRadius: '50%', background: 'linear-gradient(135deg,#4f35d2,#7c63e8)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, color: '#fff', fontWeight: 700 }}>
                AP
              </div>
              {CURRENT_AGENT.name}
            </div>
            <span style={{ fontSize: 11, color: '#7c6ea8', fontFamily: 'DM Mono, monospace', marginLeft: 'auto' }}>
              Syncs to Outlook thread
            </span>
          </div>

          <textarea
            value={replyText}
            onChange={e => setReplyText(e.target.value)}
            placeholder="Write your reply… (will appear in the Outlook thread)"
            onKeyDown={e => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSend()
            }}
            style={{
              width: '100%', minHeight: 100,
              background: '#f4f3ff', border: '1px solid #ddd8f8', borderRadius: 8,
              padding: '12px 16px', fontFamily: 'DM Mono, monospace',
              fontSize: 12, color: '#1a1340', resize: 'vertical', outline: 'none',
              lineHeight: 1.6, transition: 'border-color .15s',
            }}
            onFocus={e => { e.currentTarget.style.borderColor = '#4f35d2' }}
            onBlur={e => { e.currentTarget.style.borderColor = '#ddd8f8' }}
          />

          <div style={{ display: 'flex', alignItems: 'center', marginTop: 10 }}>
            <span style={{ fontSize: 11, color: '#7c6ea8', fontFamily: 'DM Mono, monospace' }}>
              ⌘↵ to send
            </span>
            <button
              onClick={handleSend}
              disabled={!replyText.trim() || isSending}
              style={{
                marginLeft: 'auto',
                padding: '8px 20px', borderRadius: 8,
                background: replyText.trim() ? '#4f35d2' : '#ddd8f8',
                color: replyText.trim() ? '#fff' : '#7c6ea8',
                border: 'none', fontFamily: 'Syne, sans-serif',
                fontSize: 13, fontWeight: 600, cursor: replyText.trim() ? 'pointer' : 'default',
                transition: 'all .15s',
              }}
            >
              {isSending ? 'Sending…' : 'Send Reply ⟶'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function MessageBubble({ message }: { message: Message }) {
  const isOutbound = message.direction === 'outbound'

  return (
    <div style={{ maxWidth: 680, alignSelf: isOutbound ? 'flex-end' : 'flex-start' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexDirection: isOutbound ? 'row-reverse' : 'row' }}>
        <span style={{ fontWeight: 600, fontSize: 12, color: '#3d3068' }}>
          {message.sender_name || message.sender_email}
        </span>
        <span style={{
          background: '#f4f3ff', border: '1px solid #ddd8f8', borderRadius: 4,
          padding: '1px 6px', fontSize: 10, fontFamily: 'DM Mono, monospace', color: '#7c6ea8',
        }}>
          {message.source === 'outlook' ? '📧 Outlook' : '📤 Platform → Outlook'}
        </span>
        <span style={{ fontSize: 10, color: '#7c6ea8', fontFamily: 'DM Mono, monospace' }}>
          {timeAgo(message.created_at)}
        </span>
      </div>
      <div style={{
        background: isOutbound ? '#ede9ff' : '#fff',
        border: `1px solid ${isOutbound ? '#d6cffc' : '#ddd8f8'}`,
        borderRadius: 10, padding: '16px 20px',
        fontSize: 13, lineHeight: 1.65, color: '#3d3068',
        fontFamily: 'Lora, serif', whiteSpace: 'pre-wrap',
      }}>
        {message.body_text}
      </div>
    </div>
  )
}

function MetaChip({ icon, value, mono }: { icon: string; value: string; mono?: boolean }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#7c6ea8' }}>
      <span>{icon}</span>
      <strong style={{ color: '#3d3068', fontWeight: 500, fontFamily: mono ? 'DM Mono, monospace' : undefined, fontSize: mono ? 11 : undefined }}>
        {value}
      </strong>
    </div>
  )
}

function AssigneeButton({ ticket }: { ticket: { assignee: { name: string } | null } }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 6,
      background: '#f4f3ff', border: '1px solid #ddd8f8', borderRadius: 20,
      padding: '3px 10px 3px 6px', fontSize: 11, fontWeight: 600, cursor: 'pointer',
    }}>
      <div style={{ width: 18, height: 18, borderRadius: '50%', background: 'linear-gradient(135deg,#4f35d2,#7c63e8)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, fontWeight: 700, color: '#fff' }}>
        {ticket.assignee ? ticket.assignee.name.slice(0, 2).toUpperCase() : '?'}
      </div>
      {ticket.assignee?.name ?? 'Unassigned'}
      <span style={{ color: '#7c6ea8' }}>▾</span>
    </div>
  )
}

function ActionButton({ onClick, label, primary = true }: { onClick: () => void; label: string; primary?: boolean }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: '7px 14px', borderRadius: 8,
        background: primary ? '#4f35d2' : 'transparent',
        color: primary ? '#fff' : '#3d3068',
        border: primary ? 'none' : '1px solid #ddd8f8',
        fontFamily: 'Syne, sans-serif', fontSize: 12, fontWeight: 600,
        cursor: 'pointer',
      }}
    >
      {label}
    </button>
  )
}

function EmptyState() {
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: '#7c6ea8', gap: 12, background: '#f4f3ff' }}>
      <div style={{ fontSize: 40 }}>📬</div>
      <div style={{ fontSize: 14, fontWeight: 600, color: '#3d3068' }}>Select a ticket to get started</div>
      <div style={{ fontSize: 12 }}>Your AI-powered support platform is ready</div>
    </div>
  )
}
