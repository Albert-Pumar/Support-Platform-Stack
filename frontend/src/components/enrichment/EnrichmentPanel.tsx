import { useStore } from '../../store'
import { timeAgo } from '../../utils/format'

export function EnrichmentPanel() {
  const activeTicket = useStore(s => s.activeTicket)
  const enrichment = activeTicket?.enrichment
  const classification = activeTicket

  return (
    <div style={{
      width: 280, flexShrink: 0,
      borderLeft: '1px solid #ddd8f8',
      background: '#fff',
      overflowY: 'auto',
      padding: '20px 16px',
      display: 'flex',
      flexDirection: 'column',
      gap: 20,
    }}>

      {/* AI Classification */}
      {classification?.category && (
        <Section title="✦ AI Classification">
          <div style={{ background: '#f4f3ff', border: '1px solid #ddd8f8', borderRadius: 8, padding: 12 }}>
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 6, display: 'flex', alignItems: 'center', gap: 8 }}>
              {catIcon(classification.category)} {catLabel(classification.category)}
              {classification.priority && (
                <span style={{ marginLeft: 'auto', fontFamily: 'DM Mono, monospace', fontSize: 10, color: '#7c6ea8', background: '#fff', padding: '2px 6px', borderRadius: 4 }}>
                  {classification.priority}
                </span>
              )}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {classification.tags?.map(tag => (
                <span key={tag} style={{ padding: '2px 7px', borderRadius: 4, fontSize: 10, fontWeight: 600, background: 'rgba(79,53,210,.1)', color: '#4f35d2' }}>
                  {tag}
                </span>
              ))}
              {classification.detected_language && (
                <span style={{ padding: '2px 7px', borderRadius: 4, fontSize: 10, fontWeight: 600, background: 'rgba(124,110,168,.1)', color: '#7c6ea8' }}>
                  {classification.detected_language.toUpperCase()}
                </span>
              )}
            </div>
          </div>
        </Section>
      )}

      {/* User Data */}
      <Section title="👤 User Data">
        {enrichment?.sf_user_data ? (
          <div style={{ background: '#f4f3ff', border: '1px solid #ddd8f8', borderRadius: 8, padding: 14 }}>
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 2 }}>
              {activeTicket?.sender_name || activeTicket?.sender_email}
            </div>
            <div style={{ fontSize: 11, color: '#7c6ea8', fontFamily: 'DM Mono, monospace', marginBottom: 12 }}>
              {activeTicket?.sender_email}
            </div>
            <KVRow label="Plan" value={enrichment.sf_user_data.plan} highlight />
            <KVRow label="Member since" value={enrichment.sf_user_data.created_at?.slice(0, 10)} />
            <KVRow label="Last active" value={enrichment.sf_user_data.last_active ? timeAgo(enrichment.sf_user_data.last_active) : '—'} />
            <KVRow label="Previous refunds" value={String(enrichment.sf_user_data.refund_count ?? 0)} danger={Number(enrichment.sf_user_data.refund_count) > 0} />
          </div>
        ) : (
          <Placeholder text={enrichment ? 'User not found in DB' : 'Loading user data…'} />
        )}
      </Section>

      {/* Sentry */}
      <Section title="🔴 Sentry Errors">
        {enrichment?.sentry_events?.length ? (
          enrichment.sentry_events.map(e => (
            <div key={e.id} style={{ background: '#fff5f5', border: '1px solid #fecaca', borderLeft: '3px solid #dc2626', borderRadius: 8, padding: '10px 12px', marginBottom: 8 }}>
              <div style={{ fontFamily: 'DM Mono, monospace', color: '#dc2626', fontSize: 11, fontWeight: 500, marginBottom: 4 }}>{e.title}</div>
              <div style={{ color: '#7c6ea8', fontFamily: 'DM Mono, monospace', fontSize: 10 }}>{e.dateCreated ? timeAgo(e.dateCreated) : ''}</div>
            </div>
          ))
        ) : (
          <Placeholder text={enrichment ? 'No recent errors' : 'Loading…'} />
        )}
      </Section>

      {/* PostHog */}
      <Section title="📹 Session Recordings">
        {enrichment?.posthog_recordings?.length ? (
          enrichment.posthog_recordings.map(r => (
            <a key={r.id} href={r.url} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
              <div style={{ background: '#f4f3ff', border: '1px solid #ddd8f8', borderRadius: 8, padding: 12, display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer', marginBottom: 8 }}>
                <div style={{ width: 32, height: 32, borderRadius: '50%', background: '#fff', border: '1px solid #ddd8f8', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, flexShrink: 0 }}>▶</div>
                <div style={{ fontSize: 11 }}>
                  <div style={{ fontWeight: 600, marginBottom: 2, color: '#1a1340' }}>Session recording</div>
                  <div style={{ color: '#7c6ea8', fontFamily: 'DM Mono, monospace', fontSize: 10 }}>
                    {r.start_time ? timeAgo(r.start_time) : ''} · {r.duration ? `${Math.round(r.duration)}s` : ''}
                  </div>
                </div>
              </div>
            </a>
          ))
        ) : (
          <Placeholder text={enrichment ? 'No recordings found' : 'Loading…'} />
        )}
      </Section>

      {/* Similar Tickets */}
      <Section title="🔗 Similar Past Tickets">
        {enrichment?.similar_tickets?.length ? (
          enrichment.similar_tickets.map((st, i) => (
            <div key={i} style={{ background: '#f4f3ff', border: '1px solid #ddd8f8', borderRadius: 8, padding: '10px 12px', marginBottom: 8, fontSize: 11 }}>
              <div style={{ fontFamily: 'DM Mono, monospace', color: '#7c6ea8', marginBottom: 3 }}>
                {Math.round(st.score * 100)}% match
              </div>
              <div style={{ color: '#3d3068', lineHeight: 1.4 }}>{st.reason}</div>
            </div>
          ))
        ) : (
          <Placeholder text="No similar tickets" />
        )}
      </Section>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 10, letterSpacing: '.12em', textTransform: 'uppercase', color: '#7c6ea8', marginBottom: 10, fontWeight: 700 }}>
        {title}
      </div>
      {children}
    </div>
  )
}

function KVRow({ label, value, highlight, danger }: { label: string; value?: string | null; highlight?: boolean; danger?: boolean }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 0', borderBottom: '1px solid #ddd8f8' }}>
      <span style={{ fontSize: 11, color: '#7c6ea8' }}>{label}</span>
      <span style={{ fontSize: 11, fontWeight: 600, fontFamily: 'DM Mono, monospace', color: danger ? '#dc2626' : highlight ? '#4f35d2' : '#1a1340' }}>
        {value ?? '—'}
      </span>
    </div>
  )
}

function Placeholder({ text }: { text: string }) {
  return <div style={{ fontSize: 11, color: '#7c6ea8', fontFamily: 'DM Mono, monospace', padding: '4px 0' }}>{text}</div>
}

function catIcon(cat: string): string {
  const m: Record<string, string> = { refund_request: '💸', bug_report: '🐛', billing: '💳', question: '❓', feature_request: '✨', account: '👤', other: '📋' }
  return m[cat] ?? '📋'
}

function catLabel(cat: string): string {
  return cat.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}
