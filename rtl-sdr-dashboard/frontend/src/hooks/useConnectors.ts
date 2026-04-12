import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

const API = import.meta.env.VITE_API_URL ?? '/api'

export interface Connector {
  id: string
  name: string
  protocol: string
  enabled: boolean
  frequency_hz: number | null
  gain: number | null
  sample_rate: number | null
  extra_config: Record<string, unknown> | null
  updated_at: string | null
}

export function useConnectors() {
  return useQuery<Connector[]>({
    queryKey: ['connectors'],
    queryFn: async () => {
      const res = await fetch(`${API}/connectors`)
      if (!res.ok) throw new Error('Failed to fetch connectors')
      return res.json()
    },
    refetchInterval: 15_000,
  })
}

export function useToggleConnector() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      const res = await fetch(`${API}/connectors/${id}/toggle`, { method: 'POST' })
      if (!res.ok) throw new Error('Failed to toggle connector')
      return res.json()
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['connectors'] }),
  })
}

export function usePullNow() {
  return useMutation({
    mutationFn: async (id: string) => {
      const res = await fetch(`${API}/connectors/${id}/pull`, { method: 'POST' })
      if (!res.ok) throw new Error('Failed to trigger pull')
      return res.json()
    },
  })
}

export function useUpdateConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, config }: { id: string; config: Record<string, unknown> }) => {
      const res = await fetch(`${API}/connectors/${id}/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      })
      if (!res.ok) throw new Error('Failed to update config')
      return res.json()
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['connectors'] }),
  })
}
