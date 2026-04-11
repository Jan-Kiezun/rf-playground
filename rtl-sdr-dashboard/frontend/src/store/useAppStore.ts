import { create } from 'zustand'

export interface LiveEvent {
  id: string
  type: 'rds' | 'weather' | 'adsb' | 'status' | 'noaa_image'
  connector_id?: string
  payload: Record<string, unknown>
  timestamp: string
}

interface AppState {
  wsConnected: boolean
  liveEvents: LiveEvent[]
  setWsConnected: (v: boolean) => void
  addLiveEvent: (event: LiveEvent) => void
  clearEvents: () => void
}

export const useAppStore = create<AppState>((set) => ({
  wsConnected: false,
  liveEvents: [],
  setWsConnected: (v) => set({ wsConnected: v }),
  addLiveEvent: (event) =>
    set((state) => ({
      liveEvents: [event, ...state.liveEvents].slice(0, 200),
    })),
  clearEvents: () => set({ liveEvents: [] }),
}))
