import { useState } from 'react'
import { Plug, Play, Settings, Loader2 } from 'lucide-react'
import { Connector, useToggleConnector, usePullNow, useUpdateConfig } from '../hooks/useConnectors'

interface Props {
  connector: Connector
}

export default function ConnectorCard({ connector }: Props) {
  const toggle = useToggleConnector()
  const pullNow = usePullNow()
  const updateConfig = useUpdateConfig()
  const [showConfig, setShowConfig] = useState(false)
  const [freq, setFreq] = useState(connector.frequency_hz?.toString() ?? '')
  const [gain, setGain] = useState(connector.gain?.toString() ?? '')

  const protocolColors: Record<string, string> = {
    fm: 'bg-purple-900 text-purple-200',
    rtl433: 'bg-green-900 text-green-200',
    adsb: 'bg-blue-900 text-blue-200',
    noaa: 'bg-yellow-900 text-yellow-200',
  }

  return (
    <div className="bg-gray-800 rounded-xl p-5 border border-gray-700 flex flex-col gap-4">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-lg ${protocolColors[connector.protocol] ?? 'bg-gray-700'}`}>
            <Plug size={18} />
          </div>
          <div>
            <h3 className="font-semibold text-white">{connector.name}</h3>
            <span className="text-xs text-gray-400 uppercase tracking-wider">{connector.protocol}</span>
          </div>
        </div>
        <button
          onClick={() => toggle.mutate(connector.id)}
          disabled={toggle.isPending}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
            connector.enabled ? 'bg-sky-500' : 'bg-gray-600'
          }`}
        >
          <span
            className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
              connector.enabled ? 'translate-x-6' : 'translate-x-1'
            }`}
          />
        </button>
      </div>

      <div className="flex gap-2 text-sm text-gray-400">
        {connector.frequency_hz && (
          <span className="bg-gray-700 rounded px-2 py-0.5">
            {(connector.frequency_hz / 1e6).toFixed(3)} MHz
          </span>
        )}
        {connector.sample_rate && (
          <span className="bg-gray-700 rounded px-2 py-0.5">
            {(connector.sample_rate / 1e3).toFixed(0)} ksps
          </span>
        )}
      </div>

      <div className="flex gap-2">
        <button
          onClick={() => pullNow.mutate(connector.id)}
          disabled={pullNow.isPending || !connector.enabled}
          className="flex items-center gap-1 px-3 py-1.5 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm font-medium transition-colors"
        >
          {pullNow.isPending ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
          Pull Now
        </button>
        <button
          onClick={() => setShowConfig(!showConfig)}
          className="flex items-center gap-1 px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm font-medium transition-colors"
        >
          <Settings size={14} />
          Config
        </button>
      </div>

      {showConfig && (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            updateConfig.mutate({
              id: connector.id,
              config: {
                frequency_hz: freq ? parseInt(freq) : undefined,
                gain: gain ? parseFloat(gain) : undefined,
              },
            })
          }}
          className="flex flex-col gap-2 border-t border-gray-700 pt-3"
        >
          <label className="text-xs text-gray-400">
            Frequency (Hz)
            <input
              type="number"
              value={freq}
              onChange={(e) => setFreq(e.target.value)}
              className="mt-1 block w-full bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-white focus:outline-none focus:border-sky-500"
            />
          </label>
          <label className="text-xs text-gray-400">
            Gain (dB)
            <input
              type="number"
              value={gain}
              onChange={(e) => setGain(e.target.value)}
              className="mt-1 block w-full bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-white focus:outline-none focus:border-sky-500"
            />
          </label>
          <button
            type="submit"
            disabled={updateConfig.isPending}
            className="px-3 py-1.5 bg-green-600 hover:bg-green-500 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
          >
            Save
          </button>
        </form>
      )}
    </div>
  )
}
