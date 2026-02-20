import { useStore } from '../../store'

export function Notifications() {
  const notifications = useStore(s => s.notifications)
  const dismissNotification = useStore(s => s.dismissNotification)

  return (
    <div style={{ position: 'fixed', bottom: 24, right: 24, display: 'flex', flexDirection: 'column', gap: 8, zIndex: 1000 }}>
      {notifications.map(n => (
        <div
          key={n.id}
          onClick={() => dismissNotification(n.id)}
          style={{
            display: 'flex', alignItems: 'center', gap: 10,
            padding: '10px 16px',
            background: n.type === 'ai' ? 'linear-gradient(135deg, #4f35d2, #7c63e8)' :
                        n.type === 'success' ? '#16a34a' :
                        n.type === 'warning' ? '#ea580c' : '#1a1340',
            color: '#fff',
            borderRadius: 10,
            fontSize: 13,
            fontWeight: 500,
            fontFamily: 'Syne, sans-serif',
            boxShadow: '0 4px 20px rgba(0,0,0,.15)',
            cursor: 'pointer',
            maxWidth: 320,
            animation: 'slideIn .2s ease',
          }}
        >
          {n.message}
          <span style={{ marginLeft: 'auto', opacity: 0.6, fontSize: 11 }}>✕</span>
        </div>
      ))}
      <style>{`@keyframes slideIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }`}</style>
    </div>
  )
}
