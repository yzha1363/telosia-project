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

export interface ChatDataResult {
  query_id: string
  dataset: string
  columns: string[]
  rows: Record<string, unknown>[]
  row_count: number
  truncated: boolean
  fields: Record<string, { unit?: string }>
  sources: ChatSource[]
  notice: string
  notes?: string[]
  query?: Record<string, unknown>
}

export interface ChatResponse {
  status: 'answered' | 'partial' | 'out_of_scope' | 'needs_occupation' | 'temporarily_unavailable'
  answer: string
  occupation_id: number | null
  occupation_results: ChatOccupationResult[]
  sources: ChatSource[]
  data_results?: ChatDataResult[]
  data_queries?: {
    query_id: string
    dataset: string
    row_count: number
    truncated: boolean
  }[]
  tools_used?: string[]
  request_id?: string
  timings?: ChatTiming[]
  turn_token?: string
}

export interface ChatTiming {
  stage: string
  elapsed_ms: number
  round?: number
  attempt?: number
  tool?: string
  outcome?: string
}

export type ChatStage =
  | 'understanding'
  | 'querying'
  | 'searching'
  | 'calculating'
  | 'generating'
  | 'retrying'

export interface ChatStatusEvent {
  request_id: string
  stage: ChatStage
  message: string
}

export interface ChatStreamOptions {
  signal?: AbortSignal
  timeoutMs?: number
  onStatus?: (status: ChatStatusEvent) => void
  onDelta?: (text: string) => void
  onAnswerReset?: () => void
  onDataResult?: (result: ChatDataResult) => void
}

export class ChatStreamError extends Error {
  readonly code: 'timeout' | 'cancelled' | 'network' | 'server' | 'protocol'
  readonly requestId?: string
  readonly errorCode?: string

  constructor(
    message: string,
    code: ChatStreamError['code'],
    requestId?: string,
    errorCode?: string,
  ) {
    super(message)
    this.name = 'ChatStreamError'
    this.code = code
    this.requestId = requestId
    this.errorCode = errorCode
  }
}

export interface ChatHistoryMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatRequestContext {
  history?: ChatHistoryMessage[]
  page_context?: string
  extended_analysis?: boolean
  previous_turn_token?: string
}

export function askChatbot(
  message: string,
  occupationId?: number,
  context: ChatRequestContext = {},
): Promise<ChatResponse> {
  return postJson('/chat', {
    message,
    occupation_id: occupationId,
    history: context.history ?? [],
    page_context: context.page_context,
    extended_analysis: context.extended_analysis,
    previous_turn_token: context.previous_turn_token,
  })
}

export async function askChatbotStream(
  message: string,
  occupationId?: number,
  context: ChatRequestContext = {},
  options: ChatStreamOptions = {},
): Promise<ChatResponse> {
  const controller = new AbortController()
  let timedOut = false
  let requestId: string | undefined
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined
  const abort = () => controller.abort()
  options.signal?.addEventListener('abort', abort, { once: true })
  if (options.signal?.aborted) abort()
  const started = Date.now()
  const expire = () => {
    timedOut = true
    controller.abort()
  }
  let timeout = setTimeout(expire, options.timeoutMs ?? 315_000)
  let receivedBudget = false

  try {
    // Never retry or fall back to /chat here: that could start a second paid request.
    const response = await fetch(`${API_BASE}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({
        message,
        occupation_id: occupationId,
        history: context.history ?? [],
        page_context: context.page_context,
        extended_analysis: context.extended_analysis,
        previous_turn_token: context.previous_turn_token,
      }),
      signal: controller.signal,
    })
    if (!response.ok) {
      throw new ChatStreamError(
        `The Telosia assistant could not complete the request (${response.status}). Please try again later.`,
        'server',
      )
    }
    if (!response.body || !response.headers.get('content-type')?.includes('text/event-stream')) {
      throw new ChatStreamError('The assistant returned an unexpected response. Please try again.', 'protocol')
    }

    reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let result: ChatResponse | undefined

    function processFrame(frame: string) {
      let event = 'message'
      const dataLines: string[] = []
      for (const line of frame.split(/\r?\n/)) {
        if (!line || line.startsWith(':')) continue
        const colon = line.indexOf(':')
        const field = colon < 0 ? line : line.slice(0, colon)
        const value = colon < 0 ? '' : line.slice(colon + 1).replace(/^ /, '')
        if (field === 'event') event = value
        if (field === 'data') dataLines.push(value)
      }
      if (!dataLines.length) return
      if (!['status', 'delta', 'answer_reset', 'data_result', 'result', 'error'].includes(event)) return

      let data: Record<string, unknown>
      try {
        const parsed: unknown = JSON.parse(dataLines.join('\n'))
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error()
        data = parsed as Record<string, unknown>
      } catch {
        throw new ChatStreamError('The assistant response was interrupted. Please try again.', 'protocol', requestId)
      }
      if (typeof data.request_id === 'string') requestId = data.request_id

      if (event === 'status' && typeof data.stage === 'string' && typeof data.message === 'string') {
        if (!receivedBudget && options.timeoutMs === undefined && typeof data.timeout_ms === 'number' &&
            data.timeout_ms >= 1000 && data.timeout_ms <= 315_000) {
          clearTimeout(timeout)
          timeout = setTimeout(expire, Math.max(1, started + data.timeout_ms - Date.now()))
          receivedBudget = true
        }
        options.onStatus?.({
          request_id: requestId ?? '',
          stage: data.stage as ChatStage,
          message: data.message,
        })
      } else if (event === 'delta' && typeof data.text === 'string') {
        options.onDelta?.(data.text)
      } else if (event === 'answer_reset') {
        options.onAnswerReset?.()
      } else if (event === 'data_result') {
        if (typeof data.query_id !== 'string' || typeof data.dataset !== 'string' ||
            !Array.isArray(data.rows) || !Array.isArray(data.columns) ||
            !data.columns.every((column) => typeof column === 'string') ||
            !data.rows.every((row) => row && typeof row === 'object' && !Array.isArray(row))) {
          throw new ChatStreamError('Invalid query result received.', 'protocol', requestId)
        }
        options.onDataResult?.(data as unknown as ChatDataResult)
      } else if (event === 'result') {
        if (
          typeof data.answer !== 'string' ||
          !['answered', 'partial', 'out_of_scope', 'needs_occupation', 'temporarily_unavailable'].includes(String(data.status)) ||
          !Array.isArray(data.sources) ||
          !Array.isArray(data.occupation_results)
        ) {
          throw new ChatStreamError('The assistant returned an incomplete response. Please try again.', 'protocol', requestId)
        }
        result = data as unknown as ChatResponse
      } else if (event === 'error') {
        throw new ChatStreamError(
          typeof data.message === 'string' ? data.message : 'The Telosia assistant is temporarily unavailable. Please try again later.',
          'server',
          requestId,
          typeof data.error_code === 'string' ? data.error_code : undefined,
        )
      }
    }

    while (!result) {
      const { value, done } = await reader.read()
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true })
      let boundary: RegExpExecArray | null
      while (!result && (boundary = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, boundary.index)
        buffer = buffer.slice(boundary.index + boundary[0].length)
        processFrame(frame)
      }
      if (done) break
    }
    if (!result) {
      throw new ChatStreamError('The connection ended before the answer was complete. Please try again.', 'network', requestId)
    }
    return result
  } catch (error) {
    if (timedOut) {
      throw new ChatStreamError('The assistant took too long to respond. Please try again.', 'timeout', requestId)
    }
    if (controller.signal.aborted) {
      throw new ChatStreamError('The request was cancelled. You can send your question again.', 'cancelled', requestId)
    }
    if (error instanceof ChatStreamError) throw error
    throw new ChatStreamError('Could not connect to the Telosia assistant. Please check your connection and try again.', 'network', requestId)
  } finally {
    clearTimeout(timeout)
    options.signal?.removeEventListener('abort', abort)
    if (reader) {
      void reader.cancel().catch(() => undefined)
      reader.releaseLock()
    }
  }
}
