import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../chatPresentation.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
})
const { datasetLabel, evidenceGroups, recordTurn } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)

test('labels and groups evidence without merging distinct query rows', () => {
  const first = { dataset: 'occupation_profile', query_id: 'q1', rows: [{ value: 1 }] }
  const second = { dataset: 'occupation_profile', query_id: 'q2', rows: [{ value: 2 }] }
  assert.equal(datasetLabel('occupation_profile'), 'Occupation profile')
  assert.deepEqual(evidenceGroups([first, second])[0].queries, [first, second])
  assert.deepEqual(evidenceGroups(), [])
})

test('partial turns enter history as incomplete, not as verified answer facts', () => {
  const history = recordTurn([], 'Compare jobs', { status: 'partial', answer: 'UNFINISHED NUMERIC CLAIM',
    data_queries: [{ dataset: 'occupation_profile' }] })
  assert.equal(history[0].content, 'Compare jobs')
  assert.match(history[1].content, /partial/)
  assert.match(history[1].content, /occupation_profile/)
  assert.doesNotMatch(history[1].content, /UNFINISHED NUMERIC CLAIM/)
})

test('completed answers are retained and history stays bounded', () => {
  const history = Array.from({ length: 10 }, () => ({ role: 'user', content: 'old' }))
  const next = recordTurn(history, 'Hello', { status: 'answered', answer: 'Hi' })
  assert.equal(next.length, 10)
  assert.equal(next.at(-1).content, 'Hi')
})

test('evidence uses closed details and extended retry is explicitly a new analysis', async () => {
  const component = await readFile(new URL('../../components/ChatBot.vue', import.meta.url), 'utf8')
  assert.match(component, /<details v-if="message.dataResults\?\.length" class="chatbot-query-evidence">/)
  assert.match(component, /Starts a new analysis; it does not resume the previous request/)
})
