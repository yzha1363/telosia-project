import { reactive } from 'vue'
import { API_BASE } from '../api/config'

export interface SourceRecord {
  sourceId: number
  publisher: string
  datasetTitle: string
  datasetUrl: string | null
  licence: string | null
  coveragePeriodStart: string | null
  coveragePeriodEnd: string | null
  retrievalDate: string | null
  updateFrequency: string | null
  plainLanguageNote: string | null
}

interface BackendSource {
  source_id: number
  publisher: string
  dataset_title: string
  dataset_url: string | null
  licence: string | null
  coverage_period_start: string | null
  coverage_period_end: string | null
  retrieval_date: string | null
  update_frequency: string | null
  plain_language_note: string | null
}

interface SourceDialogState {
  isOpen: boolean
  sourceId: number | null
  what: string
  source: SourceRecord | null
  isLoading: boolean
  error: string
}

export const sourceDialogState: SourceDialogState = reactive({
  isOpen: false,
  sourceId: null,
  what: '',
  source: null,
  isLoading: false,
  error: '',
})

// Maps the API's snake_case fields onto the shape the dialog renders.
function toSourceRecord(data: BackendSource): SourceRecord {
  return {
    sourceId: data.source_id,
    publisher: data.publisher,
    datasetTitle: data.dataset_title,
    datasetUrl: data.dataset_url,
    licence: data.licence,
    coveragePeriodStart: data.coverage_period_start,
    coveragePeriodEnd: data.coverage_period_end,
    retrievalDate: data.retrieval_date,
    updateFrequency: data.update_frequency,
    plainLanguageNote: data.plain_language_note,
  }
}

// Opens the source drawer and fetches the record for sourceId. A figure with no valid
// source must never render as if it were sourced, so this shows a loading state, then
// either the real record or an explicit error — never silently nothing.
export async function openSource(sourceId: number | undefined, what = '') {
  if (!sourceId) {
    throw new Error('Cannot render unsourced statistic: missing sourceId')
  }
  sourceDialogState.sourceId = sourceId
  sourceDialogState.what = what
  sourceDialogState.isOpen = true
  sourceDialogState.source = null
  sourceDialogState.error = ''
  sourceDialogState.isLoading = true
  try {
    const response = await fetch(`${API_BASE}/sources/${sourceId}`)
    if (!response.ok) throw new Error(`Source lookup failed: ${response.status}`)
    const data: BackendSource = await response.json()
    sourceDialogState.source = toSourceRecord(data)
  } catch {
    sourceDialogState.error = 'Could not load this source. Try again.'
  } finally {
    sourceDialogState.isLoading = false
  }
}

export function closeSource() {
  sourceDialogState.isOpen = false
}
