/**
 * useWebSocket
 * Auto-connecting, auto-reconnecting WebSocket hook.
 * Feeds all events into the Zustand store's handleWSEvent.
 */

import { useEffect, useRef } from 'react'
import { useStore } from '../store'
import type { WSEvent } from '../types'

const WS_URL = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/api/v1/tickets/ws`
const RECONNECT_DELAY_MS = 3000

export function useWebSocket() {
  const handleWSEvent = useStore(s => s.handleWSEvent)
  const setWsConnected = useStore(s => s.setWsConnected)
  const wsRef = useRef<WebSocket | null>(null)
  const retryTimeout = useRef<ReturnType<typeof setTimeout> | null>(null)
  const unmounted = useRef(false)

  useEffect(() => {
    unmounted.current = false
    connect()

    return () => {
      unmounted.current = true
      wsRef.current?.close()
      if (retryTimeout.current) clearTimeout(retryTimeout.current)
    }
  }, [])

  function connect() {
    if (unmounted.current) return

    const ws = new WebSocket(WS_URL)
    wsRef.current = ws

    ws.onopen = () => {
      setWsConnected(true)
      console.log('[WS] connected')
    }

    ws.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data) as WSEvent
        handleWSEvent(event)
      } catch {
        console.warn('[WS] failed to parse event', e.data)
      }
    }

    ws.onerror = () => {
      setWsConnected(false)
    }

    ws.onclose = () => {
      setWsConnected(false)
      if (!unmounted.current) {
        console.log(`[WS] disconnected, reconnecting in ${RECONNECT_DELAY_MS}ms`)
        retryTimeout.current = setTimeout(connect, RECONNECT_DELAY_MS)
      }
    }
  }
}
