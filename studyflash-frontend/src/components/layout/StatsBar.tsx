import { useStore } from '../../store'

export function StatsBar() {
  const allTickets = useStore(s => s.allTickets)

  const open = allTickets.filter(t => t.status === 'open').length
  const pending = allTickets.filter(t => t.status === 'pending').length
  const refunds = allTickets.filter(t => t.category === 'refund_request').length
  const resolved = allTickets.filter(t => t.status === 'resolved').length

  return (
    <div style={{ display: 'flex', gap: 1, background: '#ddd8f8', borderBottom: '1px solid #ddd8f8', flexShrink: 0 }}>
      {[
        { num: open, label: 'Open', color: '#2563eb' },
        { num: pending, label: 'Pending Reply', color: '#7c63e8' },
        { num: refunds, label: 'Refunds', color: '#4f35d2' },
        { num: resolved, label: 'Resolved', color: '#16a34a' },
      ].map(s => (
        <div key={s.label} style={{ flex: 1, padding: '10px 16px', background: '#fff', display: 'flex', flexDirection: 'column', gap: 2 }}>
          <div style={{ fontSize: 20, fontWeight: 800, fontFamily: 'DM Mono, monospace', color: s.color }}>{s.num}</div>
          <div style={{ fontSize: 10, color: '#7c6ea8', fontWeight: 600, letterSpacing: '.05em', textTransform: 'uppercase' }}>{s.label}</div>
        </div>
      ))}
    </div>
  )
}