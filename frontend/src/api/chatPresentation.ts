import type { ChatDataResult, ChatHistoryMessage, ChatResponse } from './telosia'

export function datasetLabel(dataset: string): string {
  const text = dataset.replaceAll('_', ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

export function evidenceGroups(results: ChatDataResult[] = []) {
  const groups = new Map<string, ChatDataResult[]>()
  for (const result of results) {
    const queries = groups.get(result.dataset) ?? []
    queries.push(result)
    groups.set(result.dataset, queries)
  }
  return [...groups].map(([dataset, queries]) => ({ dataset, label: datasetLabel(dataset), queries }))
}

export function recordTurn(history: ChatHistoryMessage[], question: string, response: Pick<ChatResponse, 'status' | 'answer' | 'data_queries'>): ChatHistoryMessage[] {
  const text = response.status === 'answered' ? response.answer :
    `[Previous analysis status: ${response.status}. Completed query datasets: ${[...new Set((response.data_queries ?? []).map(q => q.dataset))].join(', ') || 'none recorded'}. This is not a completed answer; re-query facts if needed.]`
  return [...history, { role: 'user' as const, content: question.slice(0, 4000) },
    { role: 'assistant' as const, content: text.slice(0, 4000) }].slice(-10)
}
