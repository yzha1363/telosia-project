import { API_BASE } from './config'

export interface OccupationSearchMatch {
  occupation_id: number
  title: string
}

export interface OccupationSearchResponse {
  query: string
  count: number
  matches: OccupationSearchMatch[]
  fallback_available: boolean
}

export interface BodyRegionContributor {
  variable: string
  score: number
}

export interface BodyRegionExposure {
  region: string
  score: number | null
  contributors: BodyRegionContributor[]
  message: string | null
}

export interface BodyRegionsResponse {
  occupation_id: number
  title: string
  body_regions: BodyRegionExposure[]
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`)
  if (!response.ok) throw new Error(`API request failed (${response.status})`)
  return response.json() as Promise<T>
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error(`API request failed (${response.status})`)
  return response.json() as Promise<T>
}

export function searchOccupations(query: string): Promise<OccupationSearchResponse> {
  return getJson(`/occupations/search?q=${encodeURIComponent(query)}`)
}

export function getBodyRegions(occupationId: string): Promise<BodyRegionsResponse> {
  return getJson(`/occupations/${encodeURIComponent(occupationId)}/body-regions`)
}

export interface ChatSource {
  source_id: number
  publisher: string
  dataset_title: string
  dataset_url: string | null
  licence: string | null
  plain_language_note: string | null
}

export interface ChatOccupationResult {
  occupation_id: number
  title: string
  comparison: 'higher' | 'lower'
  relative_exposure_score: number
  body_regions: string[]
  leading_demands: string[]
}

export interface ChatResponse {
  status: 'answered' | 'out_of_scope' | 'needs_occupation' | 'temporarily_unavailable'
  answer: string
  occupation_id: number | null
  occupation_results: ChatOccupationResult[]
  sources: ChatSource[]
}

export function askChatbot(message: string, occupationId?: number): Promise<ChatResponse> {
  return postJson('/chat', {
    message,
    occupation_id: occupationId,
  })
}
