import { Music2, Radio } from 'lucide-react'

interface RDSData {
  station?: string
  artist?: string
  song?: string
  genre?: string
}

interface Props {
  data: RDSData
  frequency_hz?: number
}

export default function RadioNowPlaying({ data, frequency_hz }: Props) {
  return (
    <div className="bg-gray-800 rounded-xl p-4 border border-gray-700 flex items-center gap-4">
      <div className="bg-purple-900 p-3 rounded-xl">
        <Radio className="text-purple-300" size={24} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          {frequency_hz && (
            <span className="text-xs bg-gray-700 text-gray-300 px-2 py-0.5 rounded">
              {(frequency_hz / 1e6).toFixed(1)} MHz
            </span>
          )}
          {data.station && <span className="text-sm font-bold text-purple-300">{data.station}</span>}
        </div>
        {data.song ? (
          <div className="flex items-center gap-1 text-white font-medium truncate">
            <Music2 size={14} className="text-gray-400 shrink-0" />
            <span className="truncate">
              {data.artist ? `${data.artist} — ` : ''}{data.song}
            </span>
          </div>
        ) : (
          <span className="text-gray-400 text-sm">No RDS data</span>
        )}
      </div>
    </div>
  )
}
