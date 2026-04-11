import { Thermometer, Droplets, Wind } from 'lucide-react'

interface WeatherData {
  temperature?: number
  humidity?: number
  pressure?: number
  model?: string
  time?: string
}

interface Props {
  data: WeatherData
}

export default function WeatherDisplay({ data }: Props) {
  return (
    <div className="bg-gray-800 rounded-xl p-4 border border-gray-700">
      {data.model && <p className="text-xs text-gray-400 mb-3">{data.model}</p>}
      <div className="grid grid-cols-3 gap-4">
        <div className="flex flex-col items-center gap-1">
          <Thermometer className="text-orange-400" size={20} />
          <span className="text-xl font-bold text-white">{data.temperature?.toFixed(1) ?? '--'}°C</span>
          <span className="text-xs text-gray-400">Temperature</span>
        </div>
        <div className="flex flex-col items-center gap-1">
          <Droplets className="text-blue-400" size={20} />
          <span className="text-xl font-bold text-white">{data.humidity?.toFixed(0) ?? '--'}%</span>
          <span className="text-xs text-gray-400">Humidity</span>
        </div>
        <div className="flex flex-col items-center gap-1">
          <Wind className="text-green-400" size={20} />
          <span className="text-xl font-bold text-white">{data.pressure?.toFixed(0) ?? '--'} hPa</span>
          <span className="text-xs text-gray-400">Pressure</span>
        </div>
      </div>
    </div>
  )
}
