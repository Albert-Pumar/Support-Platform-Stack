import { useState } from 'react'
import { useStore } from '../../store'
import { api } from '../../api/client'

export function AIDraftPanel() {
  const activeTicket = useStore(s => s.activeTicket)
  const isDraftPending = useStore(s => s.isDraftPending)
  const useDraft = useStore(s => s.useDraft)
  const regenerateDraft = useStore(s => s.regenerateDraft)
  const replyText = useStore(s => s.replyText)

  const [showFeedback, setShowFeedback] = useState(false)
  const [feedback, setFeedback] = useState('')

  const draft = activeTicket?.ai_draft
  const draftAlreadyInBox = replyText === draft?.draft_body

  const handleRegenerate = async (hint?: string) => {
    await regenerateDraft(hint)
    // Fallback: if no WebSocket delivers draft_regenerated within 30s,
    // stop the spinner and reload the ticket so we don't spin forever
    setTimeout(async () => {
      if (!useStore.getState().isDraftPending) return
      try {
        const ticket = await api.tickets.get(activeTicket!.id)
        useStore.setState({ activeTicket: ticket, isDraftPending: false })
      } catch {
        useStore.setState({ isDraftPending: false })
      }
    }, 30_000)
  }

  const handleDismiss = async () => {
    if (!activeTicket) return
    try {
      await api.ai.rejectDraft(activeTicket.id)
    } catch { /* non-critical */ }
    // Clear the draft locally so the panel disappears
    useStore.setState(state => ({
      activeTicket: state.activeTicket
        ? { ...state.activeTicket, ai_draft: undefined }
        : state.activeTicket,
    }))
  }

  if (isDraftPending) {
    return (
      <div style={bannerStyle}>
        <div style={aiIconStyle}>✦</div>
        <div style={{ flex: 1 }}>
          <div style={headerStyle}>✦ AI PIPELINE RUNNING…</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
            <div style={{ display: 'flex', gap: 3 }}>
              {[0, 1, 2].map(i => (
                <div key={i} style={{
                  width: 6, height: 6, borderRadius: '50%', background: '#4f35d2',
                  animation: `pulse 1.2s ease-in-out ${i * 0.2}s infinite`,
                }} />
              ))}
            </div>
            <span style={{ fontSize: 12, color: '#7c6ea8' }}>Classifying · Enriching · Drafting…</span>
          </div>
          <style>{`@keyframes pulse { 0%,100% { opacity:.3 } 50% { opacity:1 } }`}</style>
        </div>
      </div>
    )
  }

  if (!draft) return null

  return (
    <div style={bannerStyle}>
      <div style={aiIconStyle}>✦</div>
      <div style={{ flex: 1 }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
          <div style={headerStyle}>✦ AI DRAFT</div>
          {draft.confidence && (
            <span style={{ fontFamily: 'DM Mono, monospace', fontSize: 10, color: '#7c6ea8', background: '#f4f3ff', padding: '2px 7px', borderRadius: 4 }}>
              {Math.round(draft.confidence * 100)}% confidence
            </span>
          )}
          <span style={{ fontFamily: 'DM Mono, monospace', fontSize: 10, color: '#7c6ea8', marginLeft: 'auto' }}>
            {draft.model_used}
          </span>
        </div>

        {/* Draft body preview */}
        <div style={{
          fontSize: 12, color: '#3d3068', lineHeight: 1.65,
          fontFamily: 'Lora, serif', fontStyle: 'italic',
          whiteSpace: 'pre-wrap',
          maxHeight: 200, overflowY: 'auto',
          paddingRight: 4,
        }}>
          {draft.draft_body}
        </div>

        {/* Actions */}
        <div style={{ display: 'flex', gap: 8, marginTop: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          {!draftAlreadyInBox ? (
            <button onClick={useDraft} style={btnPrimary}>
              ✦ Use Draft
            </button>
          ) : (
            <span style={{ fontSize: 11, color: '#16a34a', fontWeight: 600 }}>✓ Draft in reply box</span>
          )}

          <button
            onClick={() => setShowFeedback(v => !v)}
            style={btnGhost}
          >
            ↻ Regenerate
          </button>

          <button
            onClick={handleDismiss}
            style={{ ...btnGhost, fontSize: 11, color: '#7c6ea8' }}
          >
            Dismiss
          </button>
        </div>

        {/* Feedback box for regeneration */}
        {showFeedback && (
          <div style={{ marginTop: 10, display: 'flex', gap: 8 }}>
            <input
              value={feedback}
              onChange={e => setFeedback(e.target.value)}
              placeholder="Hint: 'make it shorter', 'add refund timeline'…"
              onKeyDown={e => {
                if (e.key === 'Enter') {
                  handleRegenerate(feedback || undefined)
                  setShowFeedback(false)
                  setFeedback('')
                }
              }}
              style={{
                flex: 1, background: '#fff', border: '1px solid #ddd8f8',
                borderRadius: 6, padding: '6px 10px',
                fontFamily: 'DM Mono, monospace', fontSize: 11, color: '#1a1340',
                outline: 'none',
              }}
            />
            <button
              onClick={() => {
                handleRegenerate(feedback || undefined)
                setShowFeedback(false)
                setFeedback('')
              }}
              style={btnPrimary}
            >
              Go
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

const bannerStyle: React.CSSProperties = {
  background: 'linear-gradient(135deg, rgba(79,53,210,.05), rgba(124,99,232,.05))',
  border: '1px solid rgba(79,53,210,.15)',
  borderRadius: 10,
  padding: '14px 18px',
  display: 'flex',
  gap: 14,
  alignItems: 'flex-start',
  margin: '0 24px 0',
}

const aiIconStyle: React.CSSProperties = {
  width: 28, height: 28,
  borderRadius: 6,
  background: 'linear-gradient(135deg, #4f35d2, #7c63e8)',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  fontSize: 14, color: '#fff',
  flexShrink: 0,
  marginTop: 2,
}

const headerStyle: React.CSSProperties = {
  fontSize: 11, fontWeight: 700, color: '#4f35d2', letterSpacing: '.05em',
}

const btnPrimary: React.CSSProperties = {
  padding: '6px 14px', borderRadius: 8, background: '#4f35d2', color: '#fff',
  border: 'none', fontFamily: 'Syne, sans-serif', fontSize: 12, fontWeight: 600,
  cursor: 'pointer',
}

const btnGhost: React.CSSProperties = {
  padding: '6px 12px', borderRadius: 8, background: 'transparent',
  border: '1px solid #ddd8f8', color: '#3d3068',
  fontFamily: 'Syne, sans-serif', fontSize: 12, fontWeight: 600,
  cursor: 'pointer',
}