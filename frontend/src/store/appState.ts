import { reactive } from 'vue'
import type { BodyRegionName } from '../data/types'

interface AppState {
  selectedOccupationId: string | null
  // Comes straight from the confirm API response — not looked up in the local mock
  // occupations list, which only has 7 entries and won't have real search results.
  selectedOccupationTitle: string | null
  // No region is pre-selected on entering the risk page — nothing is shown until the
  // user actually taps one.
  activeRegion: BodyRegionName | null
}

export const appState: AppState = reactive({
  selectedOccupationId: null,
  selectedOccupationTitle: null,
  activeRegion: null,
})

export function confirmOccupation(occupationId: string, title: string) {
  appState.selectedOccupationId = occupationId
  appState.selectedOccupationTitle = title
  appState.activeRegion = null
}

export function resetSelection() {
  appState.selectedOccupationId = null
  appState.selectedOccupationTitle = null
  appState.activeRegion = null
}
