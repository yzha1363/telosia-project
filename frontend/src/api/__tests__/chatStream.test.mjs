import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

// Run with: node --test src/api/__tests__/chatStream.test.mjs
// Replace only Vite's environment-backed base URL; exercise the production stream client.
const source = (await readFile(new URL('../telosia.ts', import.meta.url), 'utf8'))
  .replace("import { API_BASE } from './config'", "const API_BASE = 'https://telosia.test/api/v1'")
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
})
const { askChatbotStream, ChatStreamError } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`
)

const answer = {
  status: 'answered',
  answer: 'Final answer with the backend disclosure.',
  occupation_id: 42,
  occupation_results: [],
  sources: [{ source_id: 1, publisher: 'Telosia', dataset_title: 'Occupation data' }],
  request_id: 'request-1',
  timings: [{ stage: 'generating', elapsed_ms: 120, round: 2 }],
}

function frame(event, data, newline = '\n') {
  return `event: ${event}${newline}data: ${JSON.stringify(data)}${newline}${newline}`
}

function streamResponse(text, byteByByte = false) {
  const bytes = new TextEncoder().encode(text)
  return new Response(new ReadableStream({
    start(controller) {
      if (byteByByte) {
        for (const byte of bytes) controller.enqueue(Uint8Array.of(byte))
      } else {
        controller.enqueue(bytes)
      }
      controller.close()
    },
  }), { headers: { 'Content-Type': 'text/event-stream; charset=utf-8' } })
}

test('delivers query evidence before model timeout without removing it on reset', async (t) => {
  const evidence = { query_id: 'q1', dataset: 'occupation', columns: ['title'],
    rows: [{ title: 'Example' }], row_count: 1, truncated: false,
    fields: {}, sources: [], notice: 'Intermediate query evidence.' }
  const events = []
  t.mock.method(globalThis, 'fetch', async () => streamResponse(
    frame('data_result', evidence) + frame('answer_reset', {}) +
    frame('result', { ...answer, status: 'temporarily_unavailable', data_results: [evidence] }), true,
  ))
  const result = await askChatbotStream('Find jobs', undefined, {}, {
    onDataResult: (data) => events.push(data), onAnswerReset: () => events.push('reset'),
  })
  assert.deepEqual(events, [evidence, 'reset'])
  assert.deepEqual(result.data_results, [evidence])
})

test('rejects malformed evidence events', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => streamResponse(
    frame('data_result', { query_id: 'q1', dataset: 'occupation', columns: ['title'], rows: [null] }),
  ))
  await assert.rejects(askChatbotStream('Find jobs'), { code: 'protocol' })
})

test('accepts partial results and forwards explicit extended retry and receipt', async (t) => {
  let body
  t.mock.method(globalThis, 'fetch', async (_url, request) => {
    body = JSON.parse(request.body)
    return streamResponse(frame('status', { stage: 'understanding', message: 'Working', timeout_ms: 315000 }) +
      frame('result', { ...answer, status: 'partial', turn_token: 'signed-receipt' }))
  })
  const response = await askChatbotStream('Compare again', undefined, {
    extended_analysis: true, previous_turn_token: 'previous-receipt',
  })
  assert.equal(body.extended_analysis, true)
  assert.equal(body.previous_turn_token, 'previous-receipt')
  assert.equal(response.status, 'partial')
  assert.equal(response.turn_token, 'signed-receipt')
})

test('handles fragmented UTF-8, CRLF, LF, heartbeats, resets, and authoritative results', async (t) => {
  let calls = 0
  let capturedRequest
  const events = []
  const text = ': keep-alive\r\n\r\n'
    + frame('status', { request_id: 'request-1', stage: 'searching', message: 'Searching occupations…' }, '\r\n')
    + frame('delta', { text: 'Café 🧑‍💻' })
    + frame('answer_reset', {})
    + 'event: delta\r\ndata: {\r\ndata: "text": "Updated draft"}\r\n\r\n'
    + frame('result', answer)
  t.mock.method(globalThis, 'fetch', async (url, request) => {
    calls += 1
    capturedRequest = { url, ...request }
    return streamResponse(text, true)
  })

  const result = await askChatbotStream('Compare roles', 42, {
    history: [{ role: 'user', content: 'Prior question' }],
    page_context: '/risk',
  }, {
    onStatus: (status) => events.push(['status', status]),
    onDelta: (delta) => events.push(['delta', delta]),
    onAnswerReset: () => events.push(['reset']),
  })

  assert.deepEqual(result, answer)
  assert.equal(calls, 1)
  assert.equal(capturedRequest.url, 'https://telosia.test/api/v1/chat/stream')
  assert.equal(capturedRequest.headers.Accept, 'text/event-stream')
  assert.deepEqual(JSON.parse(capturedRequest.body), {
    message: 'Compare roles', occupation_id: 42,
    history: [{ role: 'user', content: 'Prior question' }], page_context: '/risk',
  })
  assert.deepEqual(events, [
    ['status', { request_id: 'request-1', stage: 'searching', message: 'Searching occupations…' }],
    ['delta', 'Café 🧑‍💻'], ['reset'], ['delta', 'Updated draft'],
  ])
})

test('handles several frames in one chunk and stops on a final result', async (t) => {
  const deltas = []
  t.mock.method(globalThis, 'fetch', async () => streamResponse(
    frame('delta', { text: 'Draft' }) + frame('result', answer) + frame('delta', { text: 'Ignore' }),
  ))
  assert.deepEqual(await askChatbotStream('Question', undefined, {}, {
    onDelta: (text) => deltas.push(text),
  }), answer)
  assert.deepEqual(deltas, ['Draft'])
})

test('rejects a stream that ends with only provisional output', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => streamResponse(frame('delta', { text: 'Incomplete' })))
  await assert.rejects(askChatbotStream('Question'), (error) => (
    error instanceof ChatStreamError && error.code === 'network'
  ))
})

test('does not accept a truncated final event', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => streamResponse(frame('result', answer).trimEnd()))
  await assert.rejects(askChatbotStream('Question'), { code: 'network' })
})

test('preserves server error details after provisional output', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => streamResponse(
    frame('delta', { text: 'Provisional text' })
      + frame('error', { message: 'Request deadline reached.', request_id: 'request-2', error_code: 'deadline_exceeded' }),
  ))
  await assert.rejects(askChatbotStream('Question'), {
    code: 'server', requestId: 'request-2', errorCode: 'deadline_exceeded', message: 'Request deadline reached.',
  })
})

test('does not retry an HTTP failure or make a fallback JSON request', async (t) => {
  let calls = 0
  t.mock.method(globalThis, 'fetch', async () => {
    calls += 1
    return new Response('Service unavailable', { status: 503 })
  })
  await assert.rejects(askChatbotStream('Question'), { code: 'server' })
  assert.equal(calls, 1)
})

test('rejects malformed events and unexpected content types', async (t) => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => streamResponse('event: result\ndata: {broken}\n\n'))
  await assert.rejects(askChatbotStream('Question'), { code: 'protocol' })
  fetch.mock.mockImplementation(async () => new Response('{}', { headers: { 'Content-Type': 'application/json' } }))
  await assert.rejects(askChatbotStream('Question'), { code: 'protocol' })
})

function hangingResponse(signal) {
  return new Response(new ReadableStream({
    start(controller) {
      signal.addEventListener('abort', () => controller.error(new DOMException('Aborted', 'AbortError')), { once: true })
    },
  }), { headers: { 'Content-Type': 'text/event-stream' } })
}

test('the overall timeout aborts a stalled response body with a distinct error', async (t) => {
  let signal
  t.mock.method(globalThis, 'fetch', async (_url, options) => {
    signal = options.signal
    return hangingResponse(signal)
  })
  await assert.rejects(askChatbotStream('Question', undefined, {}, { timeoutMs: 10 }), { code: 'timeout' })
  assert.equal(signal.aborted, true)
})

test('external cancellation aborts the response body with a distinct error', async (t) => {
  t.mock.method(globalThis, 'fetch', async (_url, options) => hangingResponse(options.signal))
  const controller = new AbortController()
  const promise = askChatbotStream('Question', undefined, {}, { signal: controller.signal })
  controller.abort()
  await assert.rejects(promise, { code: 'cancelled' })
})

test('a fetch connection failure remains distinct from timeout and cancellation', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => { throw new TypeError('Failed to fetch') })
  await assert.rejects(askChatbotStream('Question'), { code: 'network' })
})
