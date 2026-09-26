<script setup lang="ts">
import ChatMarkdown from './ChatMarkdown.vue'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  askChatbotStream,
  ChatStreamError,
  type ChatHistoryMessage,
  type ChatOccupationResult,
  type ChatSource,
  type ChatDataResult,
} from '../api/telosia'
import { appState, confirmOccupation } from '../store/appState'
import { evidenceGroups, recordTurn } from '../api/chatPresentation'

interface ChatMessage {
  id: number
  role: 'assistant' | 'user'
  text: string
  occupationResults?: ChatOccupationResult[]
  sources?: ChatSource[]
  dataResults?: ChatDataResult[]
  partial?: boolean
  retryQuestion?: string
  occupationId?: number
}

interface PanelSize {
  width: number
  height: number
}

const router = useRouter()
const isOpen = ref(false)
const input = ref('')
const isSending = ref(false)
const progressMessage = ref('Understanding your question…')
const pendingMessageId = ref<number | null>(null)
const inputElement = ref<HTMLInputElement | null>(null)
const panelElement = ref<HTMLElement | null>(null)
const customPanelSize = ref<PanelSize | null>(null)
const isResizing = ref(false)
let nextMessageId = 1
let resizeOrigin: (PanelSize & { x: number; y: number }) | null = null
let activeRequest: AbortController | null = null
let isUnmounted = false

const panelStyle = computed(() => {
  if (!customPanelSize.value) return undefined
  return {
    width: `${customPanelSize.value.width}px`,
    height: `${customPanelSize.value.height}px`,
  }
})

function clampPanelSize(width: number, height: number): PanelSize {
  const maxWidth = Math.max(240, window.innerWidth - 28)
  const maxHeight = Math.max(300, window.innerHeight - 110)
  const minWidth = Math.min(320, maxWidth)
  const minHeight = Math.min(360, maxHeight)
  return {
    width: Math.min(maxWidth, Math.max(minWidth, Math.round(width))),
    height: Math.min(maxHeight, Math.max(minHeight, Math.round(height))),
  }
}

function currentPanelSize(): PanelSize | null {
  const rectangle = panelElement.value?.getBoundingClientRect()
  if (!rectangle) return null
  return { width: rectangle.width, height: rectangle.height }
}

function beginResize(event: PointerEvent) {
  if (event.pointerType === 'mouse' && event.button !== 0) return
  const size = currentPanelSize()
  if (!size) return
  resizeOrigin = {
    ...size,
    x: event.clientX,
    y: event.clientY,
  }
  customPanelSize.value = clampPanelSize(size.width, size.height)
  isResizing.value = true
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
  event.preventDefault()
}

function continueResize(event: PointerEvent) {
  if (!isResizing.value || !resizeOrigin) return
  customPanelSize.value = clampPanelSize(
    resizeOrigin.width + resizeOrigin.x - event.clientX,
    resizeOrigin.height + resizeOrigin.y - event.clientY,
  )
}

function endResize(event: PointerEvent) {
  if (!isResizing.value) return
  const target = event.currentTarget as HTMLElement
  if (target.hasPointerCapture(event.pointerId)) {
    target.releasePointerCapture(event.pointerId)
  }
  isResizing.value = false
  resizeOrigin = null
}

function resizeWithKeyboard(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    customPanelSize.value = null
    return
  }
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return
  const size = customPanelSize.value ?? currentPanelSize()
  if (!size) return
  const step = event.shiftKey ? 40 : 16
  const widthChange = event.key === 'ArrowLeft' ? step : event.key === 'ArrowRight' ? -step : 0
  const heightChange = event.key === 'ArrowUp' ? step : event.key === 'ArrowDown' ? -step : 0
  customPanelSize.value = clampPanelSize(
    size.width + widthChange,
    size.height + heightChange,
  )
  event.preventDefault()
}

function fitCustomPanelToViewport() {
  if (!customPanelSize.value) return
  customPanelSize.value = clampPanelSize(
    customPanelSize.value.width,
    customPanelSize.value.height,
  )
}

onMounted(() => window.addEventListener('resize', fitCustomPanelToViewport))
onUnmounted(() => {
  isUnmounted = true
  activeRequest?.abort()
  window.removeEventListener('resize', fitCustomPanelToViewport)
})

const messages = ref<ChatMessage[]>([
  {
    id: nextMessageId++,
    role: 'assistant',
    text: 'Explore and compare occupations, pay gaps, physical demands, injury frequency, career moves, regional employment, or AI exposure. You can ask about all Telosia data or a selected occupation.',
  },
])

const visibleMessages = computed(() => messages.value.filter((message) => (
  message.id !== pendingMessageId.value || message.text.length > 0 || message.dataResults?.length
)))

const selectedOccupationId = computed(() => {
  const value = Number(appState.selectedOccupationId)
  return Number.isInteger(value) && value > 0 ? value : undefined
})

const conversationHistory = ref<ChatHistoryMessage[]>([])
const previousTurnToken = ref<string>()
let occupationContextVersion = 0

watch(selectedOccupationId, () => {
  // Keep the visible conversation, but stop resolving "this job" against an old selection.
  conversationHistory.value = []
  previousTurnToken.value = undefined
  occupationContextVersion += 1
}, { flush: 'sync' })

async function toggleChat() {
  isOpen.value = !isOpen.value
  if (isOpen.value) {
    await nextTick()
    inputElement.value?.focus()
  }
}

function stopRequest() {
  activeRequest?.abort()
}

async function sendMessage(retryQuestion?: string, extended = false) {
  const question = (retryQuestion ?? input.value).trim()
  if (!question || isSending.value) return

  const requestContextVersion = occupationContextVersion
  const history = conversationHistory.value.slice(-10)

  messages.value.push({
    id: nextMessageId++,
    role: 'user',
    text: question,
  })
  input.value = ''
  isSending.value = true
  progressMessage.value = 'Understanding your question…'
  const controller = new AbortController()
  activeRequest = controller
  const assistantMessage = ref<ChatMessage>({
    id: nextMessageId++,
    role: 'assistant',
    text: '',
    occupationId: selectedOccupationId.value,
  })
  pendingMessageId.value = assistantMessage.value.id
  messages.value.push(assistantMessage.value)

  try {
    const response = await askChatbotStream(question, selectedOccupationId.value, {
      history,
      previous_turn_token: previousTurnToken.value,
      extended_analysis: extended,
      page_context: router.currentRoute.value.path.slice(0, 120),
    }, {
      signal: controller.signal,
      onStatus: (status) => {
        progressMessage.value = status.message
      },
      onDelta: (text) => {
        assistantMessage.value.text += text
      },
      onAnswerReset: () => {
        assistantMessage.value.text = ''
      },
      onDataResult: (result) => {
        const previous = assistantMessage.value.dataResults ?? []
        assistantMessage.value.dataResults = [...previous.filter((item) => item.query_id !== result.query_id), result]
      },
    })
    if (isUnmounted) return
    // The final response includes backend disclosures and replaces any provisional text.
    assistantMessage.value.text = response.answer
    assistantMessage.value.occupationResults = response.occupation_results
    assistantMessage.value.sources = response.sources
    if (response.data_results?.length) assistantMessage.value.dataResults = response.data_results
    assistantMessage.value.partial = response.status === 'partial' || response.status === 'temporarily_unavailable'
    if (assistantMessage.value.partial && !extended) assistantMessage.value.retryQuestion = question
    if (requestContextVersion === occupationContextVersion) {
      previousTurnToken.value = response.turn_token
      conversationHistory.value = recordTurn(history, question, response)
    }
  } catch (error) {
    if (isUnmounted) return
    assistantMessage.value.text = error instanceof ChatStreamError
      ? error.message
      : 'The Telosia assistant is temporarily unavailable. Please try again later.'
    assistantMessage.value.partial = true
    if (!extended) assistantMessage.value.retryQuestion = question
    if (requestContextVersion === occupationContextVersion) {
      previousTurnToken.value = undefined
      conversationHistory.value = recordTurn(history, question, { status: 'temporarily_unavailable', answer: '' })
    }
  } finally {
    activeRequest = null
    pendingMessageId.value = null
    isSending.value = false
    if (!isUnmounted) {
      await nextTick()
      inputElement.value?.focus()
    }
  }
}

async function viewOccupation(result: ChatOccupationResult) {
  confirmOccupation(String(result.occupation_id), result.title)
  isOpen.value = false
  await router.push('/risk')
}
</script>

<template>
  <button
    class="chatbot-toggle"
    type="button"
    :aria-expanded="isOpen"
    aria-controls="telosia-chatbot"
    aria-label="Open Telosia assistant"
    @click="toggleChat"
  >
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-5 4v-4.5A2.5 2.5 0 0 1 4 13.5z" />
      <circle cx="8" cy="9.5" r="1" />
      <circle cx="12" cy="9.5" r="1" />
      <circle cx="16" cy="9.5" r="1" />
    </svg>
  </button>

  <section
    v-if="isOpen"
    id="telosia-chatbot"
    ref="panelElement"
    class="chatbot-panel"
    :class="{ open: isOpen, resizing: isResizing }"
    :style="panelStyle"
    role="dialog"
    aria-modal="false"
    aria-labelledby="chatbot-title"
  >
    <button
      type="button"
      class="chatbot-resize-handle"
      aria-label="Resize chat window"
      title="Drag to resize. Use arrow keys to resize, or Escape to reset."
      @pointerdown="beginResize"
      @pointermove="continueResize"
      @pointerup="endResize"
      @pointercancel="endResize"
      @keydown="resizeWithKeyboard"
      @dblclick="customPanelSize = null"
    >
      <span aria-hidden="true"></span>
    </button>
    <header class="chatbot-header">
      <div>
        <p class="card-eyebrow">Data-grounded assistant</p>
        <h2 id="chatbot-title">Ask Telosia</h2>
      </div>
      <button type="button" class="chatbot-close" aria-label="Close assistant" @click="toggleChat">×</button>
    </header>

    <p class="chatbot-context">
      <template v-if="appState.selectedOccupationTitle">
        Selected: <strong>{{ appState.selectedOccupationTitle }}</strong>. You can also explore other occupations.
      </template>
      <template v-else>
        Explore all Telosia data. Selecting an occupation is optional.
      </template>
    </p>

    <div class="chatbot-messages" aria-live="polite">
      <article
        v-for="message in visibleMessages"
        :key="message.id"
        v-memo="[message.text, message.dataResults, message.sources, message.occupationResults, message.partial, message.retryQuestion, message.occupationId, selectedOccupationId, isSending, message.id === pendingMessageId]"
        class="chatbot-message"
        :class="message.role"
        :aria-busy="message.id === pendingMessageId"
      >
        <ChatMarkdown
          v-if="message.role === 'assistant'"
          class="chatbot-message-content"
          :text="message.text"
        />
        <p v-else>{{ message.text }}</p>
        <p v-if="message.partial" class="chatbot-partial">Analysis incomplete — not a finished answer.</p>
        <button v-if="message.retryQuestion && message.occupationId === selectedOccupationId" type="button" :disabled="isSending" @click="sendMessage(message.retryQuestion, true)">Retry this question · allow up to 5 minutes</button>
        <p v-if="message.retryQuestion && message.occupationId === selectedOccupationId"><small>Starts a new analysis; it does not resume the previous request.</small></p>
        <details v-if="message.dataResults?.length" class="chatbot-query-evidence">
          <summary>{{ message.id === pendingMessageId ? 'Data retrieved — analysis in progress' : 'View supporting data' }} · {{ message.dataResults.length }} queries</summary>
          <section v-for="group in evidenceGroups(message.dataResults)" :key="group.dataset">
          <h3>{{ group.label }}</h3>
          <details v-for="result in group.queries" :key="result.query_id">
          <summary>Query {{ result.query_id }} · {{ result.row_count }} returned rows</summary>
          <p>{{ result.notice }}</p>
          <p v-if="!result.row_count">No matching records were returned. No value was estimated.</p>
          <p>Showing {{ result.rows.length }} of {{ result.row_count }} returned rows.{{ result.truncated ? ' More matching rows exist.' : '' }}</p>
          <div style="overflow-x: auto; max-width: 100%">
            <table>
              <thead><tr><th v-for="column in result.columns" :key="column">{{ column }}<small v-if="result.fields?.[column]?.unit"> ({{ result.fields[column]?.unit }})</small></th></tr></thead>
              <tbody><tr v-for="(row, index) in result.rows" :key="index"><td v-for="column in result.columns" :key="column">{{ row[column] ?? 'Not published' }}</td></tr></tbody>
            </table>
          </div>
          <details v-if="result.query"><summary>Query scope</summary><pre style="white-space: pre-wrap; overflow-wrap: anywhere">{{ JSON.stringify(result.query, null, 2) }}</pre></details>
          <ul v-if="result.notes?.length"><li v-for="note in result.notes" :key="note">{{ note }}</li></ul>
          <ul><li v-for="source in result.sources" :key="source.source_id">{{ source.publisher }} — {{ source.dataset_title }}</li></ul>
          </details>
          </section>
        </details>
        <div
          v-if="message.occupationResults?.length"
          class="chatbot-occupation-results"
          aria-label="Matching occupations"
        >
          <article
            v-for="result in message.occupationResults"
            :key="result.occupation_id"
            class="chatbot-occupation-card"
          >
            <div>
              <h3>{{ result.title }}</h3>
              <p>
                {{ result.comparison === 'lower' ? 'Lower' : 'Higher' }} recorded
                relative exposure · {{ result.relative_exposure_score }}/100
              </p>
            </div>
            <ul>
              <li v-for="demand in result.leading_demands" :key="demand">
                {{ demand }}
              </li>
            </ul>
            <button type="button" @click="viewOccupation(result)">
              View occupation
            </button>
          </article>
        </div>
        <details v-if="message.sources?.length" class="chatbot-sources">
          <summary>Supporting data sources ({{ message.sources.length }})</summary>
          <ul>
            <li v-for="source in message.sources" :key="source.source_id">
              <a v-if="source.dataset_url" :href="source.dataset_url" target="_blank" rel="noopener noreferrer">
                {{ source.publisher }} — {{ source.dataset_title }}
              </a>
              <span v-else>{{ source.publisher }} — {{ source.dataset_title }}</span>
            </li>
          </ul>
        </details>
      </article>
      <p v-if="isSending" class="chatbot-thinking" role="status">{{ progressMessage }}</p>
    </div>

    <form class="chatbot-form" @submit.prevent="sendMessage()">
      <label class="sr" for="chatbot-input">Ask a question about Telosia data</label>
      <input
        id="chatbot-input"
        ref="inputElement"
        v-model="input"
        type="text"
        maxlength="2000"
        autocomplete="off"
        placeholder="Ask, compare, or explore Telosia data…"
        :disabled="isSending"
      />
      <button v-if="isSending" type="button" @click="stopRequest">Stop</button>
      <button v-else type="submit" :disabled="!input.trim()">Send</button>
    </form>
    <p class="chatbot-disclaimer">Uses published Telosia data. Not medical advice or a personal risk prediction.</p>
  </section>
</template>

<style scoped>
.chatbot-query-evidence {
  min-width: 0;
  margin-top: 1rem;
  padding: 0.75rem;
  border: 1px solid #d9b9d0;
  border-radius: 0.5rem;
  background: #fff;
}
.chatbot-query-evidence table { border-collapse: collapse; width: 100%; font-size: 0.85rem; }
.chatbot-query-evidence th, .chatbot-query-evidence td {
  text-align: left;
  vertical-align: top;
  padding: 0.5rem;
  border-bottom: 1px solid #eadce5;
  min-width: 6rem;
  overflow-wrap: anywhere;
}
.chatbot-query-evidence h3 { font-size: 1rem; }
.chatbot-query-evidence p, .chatbot-query-evidence li { font-size: 0.85rem; }
</style>
