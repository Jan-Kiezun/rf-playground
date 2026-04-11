import { useEffect, useRef, useState } from 'react'
import Hls from 'hls.js'
import { Play, Pause, Volume2, Radio } from 'lucide-react'
import { useAppStore } from '../store/useAppStore'

const PRESETS = [
  { label: 'Local FM', freq: 98.1 },
  { label: 'NOAA 1', freq: 162.4 },
  { label: 'NOAA 2', freq: 162.55 },
]

const API = import.meta.env.VITE_API_URL ?? '/api'

export default function RadioPlayer() {
  const audioRef = useRef<HTMLAudioElement>(null)
  const hlsRef = useRef<Hls | null>(null)
  const [playing, setPlaying] = useState(false)
  const [volume, setVolume] = useState(0.8)
  const [frequency, setFrequency] = useState('98.1')
  const [status, setStatus] = useState<string>('Idle')

  const liveEvents = useAppStore((s) => s.liveEvents)
  const lastRds = liveEvents.find((e) => e.type === 'rds')

  useEffect(() => {
    return () => {
      hlsRef.current?.destroy()
    }
  }, [])

  function startStream() {
    const freqHz = Math.round(parseFloat(frequency) * 1e6)
    fetch(`${API}/audio/start?frequency_hz=${freqHz}`, { method: 'POST' })
      .then(() => {
        setStatus('Starting HLS stream…')
        setTimeout(attachHls, 5000)
      })
      .catch(() => setStatus('Failed to start stream'))
  }

  function attachHls() {
    const audio = audioRef.current
    if (!audio) return

    if (Hls.isSupported()) {
      const hls = new Hls({ lowLatencyMode: true })
      hls.loadSource('/stream/radio.m3u8')
      hls.attachMedia(audio)
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        audio.play().catch(() => {})
        setPlaying(true)
        setStatus('Streaming')
      })
      hls.on(Hls.Events.ERROR, (_e, data) => {
        if (data.fatal) {
          setStatus('Stream error')
          setPlaying(false)
        }
      })
      hlsRef.current = hls
    } else if (audio.canPlayType('application/vnd.apple.mpegurl')) {
      audio.src = '/stream/radio.m3u8'
      audio.play().catch(() => {})
      setPlaying(true)
      setStatus('Streaming (native HLS)')
    }
  }

  function stopStream() {
    hlsRef.current?.destroy()
    hlsRef.current = null
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.src = ''
    }
    fetch(`${API}/audio/stop`, { method: 'POST' }).catch(() => {})
    setPlaying(false)
    setStatus('Stopped')
  }

  function handleVolumeChange(v: number) {
    setVolume(v)
    if (audioRef.current) audioRef.current.volume = v
  }

  return (
    <div className="space-y-6 max-w-2xl mx-auto">
      <h1 className="text-2xl font-bold text-white">FM Radio Player</h1>

      <div className="bg-gray-800 rounded-xl p-6 border border-gray-700 space-y-5">
        <div className="flex items-center gap-4">
          <div className="bg-purple-900 p-4 rounded-xl">
            <Radio className="text-purple-300" size={28} />
          </div>
          <div>
            <p className="text-lg font-bold text-white">
              {parseFloat(frequency).toFixed(1)} MHz FM
            </p>
            <p className="text-sm text-gray-400">{status}</p>
          </div>
        </div>

        <div>
          <label className="text-xs text-gray-400 block mb-1">Frequency (MHz)</label>
          <div className="flex gap-2">
            <input
              type="number"
              value={frequency}
              step="0.1"
              min="76"
              max="108"
              onChange={(e) => setFrequency(e.target.value)}
              className="flex-1 bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-sky-500"
            />
            <div className="flex gap-1">
              {PRESETS.map((p) => (
                <button
                  key={p.freq}
                  onClick={() => setFrequency(String(p.freq))}
                  className="px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded text-xs text-gray-300 transition-colors"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <button
            onClick={playing ? stopStream : startStream}
            className={`flex items-center gap-2 px-5 py-2.5 rounded-xl font-semibold transition-colors ${
              playing
                ? 'bg-red-600 hover:bg-red-500 text-white'
                : 'bg-sky-600 hover:bg-sky-500 text-white'
            }`}
          >
            {playing ? <Pause size={18} /> : <Play size={18} />}
            {playing ? 'Stop' : 'Play'}
          </button>

          <div className="flex items-center gap-2 flex-1">
            <Volume2 size={16} className="text-gray-400 shrink-0" />
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={volume}
              onChange={(e) => handleVolumeChange(parseFloat(e.target.value))}
              className="flex-1 accent-sky-500"
            />
          </div>
        </div>

        {lastRds && (
          <div className="bg-gray-900 rounded-lg p-3 border border-gray-700">
            <p className="text-xs text-gray-400 mb-1">RDS Data</p>
            <p className="text-sm text-gray-200 font-mono">
              {JSON.stringify(lastRds.payload, null, 2).slice(0, 200)}
            </p>
          </div>
        )}
      </div>

      <audio ref={audioRef} className="hidden" />
    </div>
  )
}
