import { useEffect, useState } from 'react'
import { useStore } from './store'
import { useWebSocket } from './hooks/useWebSocket'
import { Sidebar } from './components/layout/Sidebar'
import { StatsBar } from './components/layout/StatsBar'
import { Notifications } from './components/layout/Notifications'
import { TicketList } from './components/tickets/TicketList'
import { TicketDetail } from './components/tickets/TicketDetail'
import { EnrichmentPanel } from './components/enrichment/EnrichmentPanel'

export default function App() {
  const fetchTickets = useStore(s => s.fetchTickets)
  const activeTicket = useStore(s => s.activeTicket)
  const [activeView, setActiveView] = useState('All Tickets')
  const [showEnrichment, setShowEnrichment] = useState(false)

  useWebSocket()

  useEffect(() => {
    fetchTickets()
    const interval = setInterval(fetchTickets, 60_000)
    return () => clearInterval(interval)
  }, [])

  // Auto-hide enrichment panel when no ticket is selected
  useEffect(() => {
    if (!activeTicket) setShowEnrichment(false)
  }, [activeTicket])

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden', fontFamily: 'Syne, sans-serif' }}>
      <Sidebar activeView={activeView} onViewChange={setActiveView} />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
        {/* Topbar */}
        <div style={{
          background: '#fff', borderBottom: '1px solid #ddd8f8',
          padding: '14px 24px', display: 'flex', alignItems: 'center', gap: 16, flexShrink: 0,
        }}>
          <h1 style={{ fontSize: 16, fontWeight: 700, color: '#1a1340', margin: 0 }}>{activeView}</h1>
          <div style={{ flex: 1 }} />
          {activeTicket && (
            <button
              onClick={() => setShowEnrichment(v => !v)}
              style={{
                padding: '7px 14px', borderRadius: 8, cursor: 'pointer',
                fontFamily: 'Syne, sans-serif', fontSize: 12, fontWeight: 600,
                border: '1px solid #ddd8f8',
                background: showEnrichment ? '#4f35d2' : 'transparent',
                color: showEnrichment ? '#fff' : '#3d3068',
                transition: 'all 0.15s',
              }}
            >
              {showEnrichment ? '✦ Hide Context' : '✦ Show Context'}
            </button>
          )}
          <button
            onClick={fetchTickets}
            style={{ padding: '7px 14px', borderRadius: 8, background: 'transparent', border: '1px solid #ddd8f8', color: '#3d3068', fontFamily: 'Syne, sans-serif', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}
          >
            ⇄ Refresh
          </button>
        </div>

        <StatsBar />

        {/* Content columns */}
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minWidth: 0 }}>
          <TicketList />
          <TicketDetail />
          {showEnrichment && activeTicket && <EnrichmentPanel />}
        </div>
      </div>

      <Notifications />
    </div>
  )
}