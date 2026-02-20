import { useStore } from '../../store'

const NAV = [
  { icon: '📬', label: 'All Tickets', filter: undefined },
  { icon: '🔴', label: 'Unassigned', filter: 'open' as const },
  { icon: '🙋', label: 'My Tickets', filter: undefined },
]

const VIEWS = [
  { icon: '💸', label: 'Refund Requests', category: 'refund_request' as const },
  { icon: '🐛', label: 'Bug Reports', category: 'bug_report' as const },
  { icon: '✅', label: 'Resolved', status: 'resolved' as const },
]

interface Props {
  activeView: string
  onViewChange: (view: string) => void
}

export function Sidebar({ activeView, onViewChange }: Props) {
  const tickets = useStore(s => s.tickets)
  const wsConnected = useStore(s => s.wsConnected)
  const setFilter = useStore(s => s.setFilter)

  const openCount = tickets.filter(t => t.status === 'open').length

  return (
    <aside style={{
      width: 220,
      flexShrink: 0,
      background: 'linear-gradient(180deg, #3a28b0 0%, #4f35d2 60%, #6347e0 100%)',
      display: 'flex',
      flexDirection: 'column',
      padding: '20px 0',
      position: 'relative',
    }}>
      {/* Logo */}
      <div style={{ padding: '0 20px 24px', display: 'flex', alignItems: 'center', gap: 10, borderBottom: '1px solid rgba(255,255,255,.15)' }}>
        <div style={{ width: 30, height: 30, background: 'rgba(255,255,255,.2)', borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 800, color: '#fff', flexShrink: 0 }}>
          SF
        </div>
        <div style={{ fontSize: 13, fontWeight: 700, color: '#fff', lineHeight: 1.2 }}>
          Studyflash
          <span style={{ color: 'rgba(255,255,255,.6)', fontWeight: 400, fontSize: 11, display: 'block' }}>Support Platform</span>
        </div>
      </div>

      {/* Nav */}
      <nav style={{ padding: '16px 10px', flex: 1 }}>
        <SectionLabel>Inbox</SectionLabel>
        {NAV.map(item => (
          <NavItem
            key={item.label}
            icon={item.icon}
            label={item.label}
            active={activeView === item.label}
            badge={item.label === 'All Tickets' ? openCount : undefined}
            onClick={() => {
              onViewChange(item.label)
              setFilter('status', item.filter)
            }}
          />
        ))}

        <SectionLabel>Views</SectionLabel>
        {VIEWS.map(item => (
          <NavItem
            key={item.label}
            icon={item.icon}
            label={item.label}
            active={activeView === item.label}
            onClick={() => {
              onViewChange(item.label)
              if (item.category) setFilter('category', item.category)
              if (item.status) setFilter('status', item.status)
            }}
          />
        ))}

        <SectionLabel>Team</SectionLabel>
        <NavItem icon="⚙️" label="Settings" active={false} onClick={() => {}} />
      </nav>

      {/* WS status + footer */}
      <div style={{ padding: '10px 20px 0', borderTop: '1px solid rgba(255,255,255,.15)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12 }}>
          <div style={{ width: 6, height: 6, borderRadius: '50%', background: wsConnected ? '#4ade80' : '#f87171', flexShrink: 0 }} />
          <span style={{ fontSize: 10, color: 'rgba(255,255,255,.5)', fontFamily: 'DM Mono, monospace' }}>
            {wsConnected ? 'Live' : 'Reconnecting…'}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 28, height: 28, borderRadius: '50%', background: 'rgba(255,255,255,.25)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, color: 'white', flexShrink: 0 }}>AP</div>
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: '#fff' }}>Albert Pumar</div>
            <div style={{ fontSize: 10, color: 'rgba(255,255,255,.55)' }}>Platform Engineer Intern</div>
          </div>
        </div>
      </div>
    </aside>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 10, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(255,255,255,.45)', padding: '0 10px', margin: '16px 0 6px' }}>
      {children}
    </div>
  )
}

function NavItem({ icon, label, active, badge, onClick }: {
  icon: string; label: string; active: boolean; badge?: number; onClick: () => void
}) {
  return (
    <div
      onClick={onClick}
      style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '8px 10px', borderRadius: 8, cursor: 'pointer',
        fontSize: 13, fontWeight: 500,
        color: active ? '#fff' : 'rgba(255,255,255,.7)',
        background: active ? 'rgba(255,255,255,.2)' : 'transparent',
        transition: 'all .15s',
        userSelect: 'none',
      }}
      onMouseEnter={e => { if (!active) (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,.1)' }}
      onMouseLeave={e => { if (!active) (e.currentTarget as HTMLElement).style.background = 'transparent' }}
    >
      <span style={{ fontSize: 15, width: 18, textAlign: 'center' }}>{icon}</span>
      {label}
      {badge !== undefined && badge > 0 && (
        <span style={{ marginLeft: 'auto', background: 'rgba(255,255,255,.25)', color: '#fff', fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 20 }}>
          {badge}
        </span>
      )}
    </div>
  )
}
