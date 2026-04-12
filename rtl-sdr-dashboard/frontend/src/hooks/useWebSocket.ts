import { useEffect, useRef } from 'react'
import { useAppStore } from '../store/useAppStore'

const WS_URL = import.meta.env.VITE_WS_URL ?? 'ws://localhost/ws'

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null)
  const { setWsConnected, addLiveEvent } = useAppStore()

  useEffect(() => {
    function connect() {
      const ws = new WebSocket(`${WS_URL}/live`)
      wsRef.current = ws

      ws.onopen = () => setWsConnected(true)
      ws.onclose = () => {
        setWsConnected(false)
        setTimeout(connect, 3000)
      }
      ws.onerror = () => ws.close()
      ws.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data as string)
          addLiveEvent({
            id: crypto.randomUUID(),
            type: parsed.type ?? 'status',
            connector_id: parsed.connector_id,
            payload: parsed.data ?? parsed,
            timestamp: new Date().toISOString(),
          })
        } catch {
          // ignore malformed messages
        }
      }
    }
    connect()
    return () => {
      wsRef.current?.close()
    }
  }, [setWsConnected, addLiveEvent])
}
