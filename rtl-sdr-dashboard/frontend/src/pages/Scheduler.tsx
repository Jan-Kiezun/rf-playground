import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, Plus, Trash2, ToggleLeft, ToggleRight, Loader2 } from 'lucide-react'
import { useConnectors } from '../hooks/useConnectors'
import DataTable from '../components/DataTable'

const API = import.meta.env.VITE_API_URL ?? '/api'

interface Job {
  id: string
  connector_id: string | null
  cron_expression: string | null
  enabled: boolean
  last_run: string | null
  next_run: string | null
}

export default function Scheduler() {
  const qc = useQueryClient()
  const { data: connectors } = useConnectors()
  const [connectorId, setConnectorId] = useState('')
  const [cron, setCron] = useState('0 */90 * * *')

  const { data: jobs, isLoading } = useQuery<Job[]>({
    queryKey: ['schedule'],
    queryFn: async () => {
      const res = await fetch(`${API}/schedule`)
      return res.json()
    },
    refetchInterval: 30_000,
  })

  const createJob = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API}/schedule`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ connector_id: connectorId, cron_expression: cron, enabled: true }),
      })
      if (!res.ok) throw new Error('Failed to create job')
      return res.json()
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['schedule'] }),
  })

  const deleteJob = useMutation({
    mutationFn: async (id: string) => {
      await fetch(`${API}/schedule/${id}`, { method: 'DELETE' })
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['schedule'] }),
  })

  const toggleJob = useMutation({
    mutationFn: async (id: string) => {
      await fetch(`${API}/schedule/${id}/toggle`, { method: 'PATCH' })
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['schedule'] }),
  })

  const connectorName = (id: string | null) => {
    if (!id) return '—'
    return connectors?.find((c) => c.id === id)?.name ?? id
  }

  const columns = [
    { key: 'connector_id' as keyof Job, label: 'Connector', render: (v: Job[keyof Job]) => connectorName(v as string | null) },
    { key: 'cron_expression' as keyof Job, label: 'Schedule', render: (v: Job[keyof Job]) => <code className="font-mono text-xs text-green-300">{String(v ?? '—')}</code> },
    { key: 'enabled' as keyof Job, label: 'Status', render: (v: Job[keyof Job]) => (
      <span className={`text-xs px-2 py-0.5 rounded-full ${v ? 'bg-green-900 text-green-300' : 'bg-gray-700 text-gray-400'}`}>
        {v ? 'Enabled' : 'Disabled'}
      </span>
    )},
    { key: 'last_run' as keyof Job, label: 'Last Run', render: (v: Job[keyof Job]) => v ? new Date(v as string).toLocaleString() : '—' },
    { key: 'next_run' as keyof Job, label: 'Next Run', render: (v: Job[keyof Job]) => v ? new Date(v as string).toLocaleString() : '—' },
    { key: 'id' as keyof Job, label: 'Actions', render: (_v: Job[keyof Job], row: Job) => (
      <div className="flex gap-2">
        <button
          onClick={() => toggleJob.mutate(row.id)}
          className="text-gray-400 hover:text-white transition-colors"
          title={row.enabled ? 'Disable' : 'Enable'}
        >
          {row.enabled ? <ToggleRight size={16} className="text-green-400" /> : <ToggleLeft size={16} />}
        </button>
        <button
          onClick={() => deleteJob.mutate(row.id)}
          className="text-gray-400 hover:text-red-400 transition-colors"
          title="Delete"
        >
          <Trash2 size={16} />
        </button>
      </div>
    )},
  ]

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Scheduler</h1>

      <div className="bg-gray-800 rounded-xl p-5 border border-gray-700 space-y-4">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-2">
          <Plus size={16} />
          Add Scheduled Job
        </h2>
        <form
          onSubmit={(e) => { e.preventDefault(); createJob.mutate() }}
          className="flex flex-wrap gap-3 items-end"
        >
          <label className="flex flex-col gap-1 min-w-48">
            <span className="text-xs text-gray-400">Connector</span>
            <select
              value={connectorId}
              onChange={(e) => setConnectorId(e.target.value)}
              required
              className="bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-sky-500"
            >
              <option value="">Select connector…</option>
              {connectors?.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 min-w-48">
            <span className="text-xs text-gray-400">Cron Expression</span>
            <input
              type="text"
              value={cron}
              onChange={(e) => setCron(e.target.value)}
              placeholder="0 */90 * * *"
              className="bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-sky-500"
            />
          </label>
          <button
            type="submit"
            disabled={createJob.isPending}
            className="flex items-center gap-2 px-4 py-2 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
          >
            {createJob.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            Add Job
          </button>
        </form>
      </div>

      <div className="bg-gray-800 rounded-xl p-5 border border-gray-700">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4 flex items-center gap-2">
          <CalendarClock size={16} />
          Scheduled Jobs
        </h2>
        {isLoading ? (
          <div className="flex justify-center py-8"><Loader2 className="animate-spin text-sky-400" size={24} /></div>
        ) : (
          <DataTable columns={columns} data={jobs ?? []} emptyMessage="No scheduled jobs. Add one above." />
        )}
      </div>
    </div>
  )
}
