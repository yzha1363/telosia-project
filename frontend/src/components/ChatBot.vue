<script setup lang="ts">
import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  askChatbot,
  type ChatOccupationResult,
  type ChatSource,
} from '../api/telosia'
import { appState, confirmOccupation } from '../store/appState'

interface ChatMessage {
  id: number
  role: 'assistant' | 'user'
  text: string
  occupationResults?: ChatOccupationResult[]
  sources?: ChatSource[]
}

interface PanelSize {
  width: number
  height: number
}

const router = useRouter()
const isOpen = ref(false)
const input = ref('')
const isSending = ref(false)
const inputElement = ref<HTMLInputElement | null>(null)
const panelElement = ref<HTMLElement | null>(null)
const customPanelSize = ref<PanelSize | null>(null)
const isResizing = ref(false)
let nextMessageId = 1
let resizeOrigin: (PanelSize & { x: number; y: number }) | null = null

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
onUnmounted(() => window.removeEventListener('resize', fitCustomPanelToViewport))

const markdown = new MarkdownIt({
  breaks: true,
  html: false,
  linkify: true,
  typographer: false,
})

function renderAssistantMessage(text: string): string {
  return DOMPurify.sanitize(markdown.render(text), {
    USE_PROFILES: { html: true },
  })
}

const messages = ref<ChatMessage[]>([
  {
    id: nextMessageId++,
    role: 'assistant',
    text: 'Ask me about occupations, physical-demand exposure, injury frequency, career moves, or Telosia data sources.',
  },
])

const selectedOccupationId = computed(() => {
  const value = Number(appState.selectedOccupationId)
  return Number.isInteger(value) && value > 0 ? value : undefined
})

async function toggleChat() {
  isOpen.value = !isOpen.value
  if (isOpen.value) {
    await nextTick()
    inputElement.value?.focus()
  }
}

async function sendMessage() {
  const question = input.value.trim()
  if (!question || isSending.value) return

  messages.value.push({
    id: nextMessageId++,
    role: 'user',
    text: question,
  })
  input.value = ''
  isSending.value = true

  try {
    const response = await askChatbot(question, selectedOccupationId.value)
    messages.value.push({
      id: nextMessageId++,
      role: 'assistant',
      text: response.answer,
      occupationResults: response.occupation_results,
      sources: response.sources,
    })
  } catch {
    messages.value.push({
      id: nextMessageId++,
      role: 'assistant',
      text: 'The Telosia assistant is temporarily unavailable. Please try again later.',
    })
  } finally {
    isSending.value = false
    await nextTick()
    inputElement.value?.focus()
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
        Using data for <strong>{{ appState.selectedOccupationTitle }}</strong>
      </template>
      <template v-else>
        No occupation selected — answers will be general.
      </template>
    </p>

    <div class="chatbot-messages" aria-live="polite">
      <article
        v-for="message in messages"
        :key="message.id"
        class="chatbot-message"
        :class="message.role"
      >
        <div
          v-if="message.role === 'assistant'"
          class="chatbot-message-content"
          v-html="renderAssistantMessage(message.text)"
        ></div>
        <p v-else>{{ message.text }}</p>
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
      <p v-if="isSending" class="chatbot-thinking">Checking Telosia data…</p>
    </div>

    <form class="chatbot-form" @submit.prevent="sendMessage">
      <label class="sr" for="chatbot-input">Ask a question about Telosia data</label>
      <input
        id="chatbot-input"
        ref="inputElement"
        v-model="input"
        type="text"
        maxlength="500"
        autocomplete="off"
        :placeholder="selectedOccupationId ? 'Ask about this occupation…' : 'Ask a general Telosia question…'"
        :disabled="isSending"
      />
      <button type="submit" :disabled="isSending || !input.trim()">Send</button>
    </form>
    <p class="chatbot-disclaimer">Uses published Telosia data. Not medical advice or a personal risk prediction.</p>
  </section>
</template>
