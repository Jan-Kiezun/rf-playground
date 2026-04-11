import { useQuery } from '@tanstack/react-query'
import { Wifi, WifiOff, Activity, Clock, Layers } from 'lucide-react'
import { useWebSocket } from '../hooks/useWebSocket'
import { useAppStore, LiveEvent } from '../store/useAppStore'
import { useConnectors } from '../hooks/useConnectors'
import SignalChart from '../components/SignalChart'

const API = import.meta.env.VITE_API_URL ?? '/api'

function StatusCard({ label, value, icon: Icon, color }: { label: string; value: string | number; icon: React.ElementType; color: string }) {
  return (
    <div className="bg-gray-800 rounded-xl p-5 border border-gray-700 flex items-center gap-4">
      <div className={`p-3 rounded-xl ${color}`}>
        <Icon size={22} />
      </div>
      <div>
        <p className="text-gray-400 text-sm">{label}</p>
        <p className="text-xl font-bold text-white">{value}</p>
      </div>
    </div>
  )
}

function EventBadge({ type }: { type: LiveEvent['type'] }) {
  const colors: Record<string, string> = {
    rds: 'bg-purple-800 text-purple-200',
    weather: 'bg-green-800 text-green-200',
    adsb: 'bg-blue-800 text-blue-200',
    noaa_image: 'bg-yellow-800 text-yellow-200',
    status: 'bg-gray-700 text-gray-300',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded font-mono uppercase ${colors[type] ?? colors.status}`}>
      {type}
    </span>
  )
}

export default function Dashboard() {
  useWebSocket()
  const { wsConnected, liveEvents } = useAppStore()
  const { data: connectors } = useConnectors()

  const { data: deviceStatus } = useQuery({
    queryKey: ['device-status'],
    queryFn: async () => {
      const res = await fetch(`${API}/device/status`)
      return res.json()
    },
    refetchInterval: 30_000,
  })

  const activeConnectors = connectors?.filter((c) => c.enabled).length ?? 0
  const totalConnectors = connectors?.length ?? 0

  // Build mini chart data from weather events
  const weatherEvents = liveEvents
    .filter((e) => e.type === 'weather' && (e.payload as Record<string, unknown>).temperature_C)
    .slice(0, 20)
    .reverse()
    .map((e, i) => ({
      time: new Date(e.timestamp).toLocaleTimeString(),
      value: Number((e.payload as Record<string, unknown>).temperature_C ?? 0),
    }))

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Dashboard</h1>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatusCard
          label="Device"
          value={deviceStatus?.connected ? 'Connected' : 'Disconnected'}
          icon={deviceStatus?.connected ? Wifi : WifiOff}
          color={deviceStatus?.connected ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'}
        />
        <StatusCard
          label="Active Connectors"
          value={`${activeConnectors} / ${totalConnectors}`}
          icon={Layers}
          color="bg-sky-900 text-sky-300"
        />
        <StatusCard
          label="Live Feed"
          value={wsConnected ? 'Live' : 'Offline'}
          icon={Activity}
          color={wsConnected ? 'bg-green-900 text-green-300' : 'bg-gray-700 text-gray-400'}
        />
        <StatusCard
          label="Events Received"
          value={liveEvents.length}
          icon={Clock}
          color="bg-indigo-900 text-indigo-300"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {weatherEvents.length > 0 && (
          <div className="bg-gray-800 rounded-xl p-5 border border-gray-700">
            <h2 className="text-sm font-semibold text-gray-400 mb-3 uppercase tracking-wider">Temperature Feed</h2>
            <SignalChart data={weatherEvents} label="Temperature (°C)" color="#f97316" />
          </div>
        )}

        <div className="bg-gray-800 rounded-xl p-5 border border-gray-700">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">Live Signal Feed</h2>
            <span className={`text-xs px-2 py-0.5 rounded-full ${wsConnected ? 'bg-green-900 text-green-300' : 'bg-gray-700 text-gray-400'}`}>
              {wsConnected ? '● LIVE' : '○ OFFLINE'}
            </span>
          </div>
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {liveEvents.length === 0 ? (
              <p className="text-gray-500 text-sm text-center py-8">Waiting for live data…</p>
            ) : (
              liveEvents.map((event) => (
                <div key={event.id} className="flex items-start gap-2 text-xs">
                  <span className="text-gray-500 shrink-0 font-mono">
                    {new Date(event.timestamp).toLocaleTimeString()}
                  </span>
                  <EventBadge type={event.type} />
                  <span className="text-gray-300 truncate font-mono">
                    {JSON.stringify(event.payload).slice(0, 80)}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
