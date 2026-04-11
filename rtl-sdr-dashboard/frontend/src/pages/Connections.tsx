import { useConnectors } from '../hooks/useConnectors'
import ConnectorCard from '../components/ConnectorCard'
import { Loader2 } from 'lucide-react'

export default function Connections() {
  const { data: connectors, isLoading, error } = useConnectors()

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="animate-spin text-sky-400" size={32} />
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-red-400 text-center py-12">Failed to load connectors. Is the backend running?</div>
    )
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Connections & Configuration</h1>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
        {connectors?.map((connector) => (
          <ConnectorCard key={connector.id} connector={connector} />
        ))}
      </div>
      {(!connectors || connectors.length === 0) && (
        <p className="text-gray-400 text-center py-12">No connectors configured. Seed the database first.</p>
      )}
    </div>
  )
}
