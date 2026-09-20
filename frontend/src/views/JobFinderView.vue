<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import type { Occupation } from '../data/types'
import { confirmOccupation } from '../store/appState'
import { normalize, type OccupationMatch } from '../utils/searchOccupations'
import { API_BASE } from '../api/config'

const router = useRouter()

interface BackendOccupationMatch {
  occupation_id: number
  title: string
}

interface BackendSearchResponse {
  query: string
  count: number
  matches: BackendOccupationMatch[]
  fallback_available: boolean
  message: string | null
}

interface BackendOccupationDetail {
  id: number
  title: string
}

const inputEl = ref<HTMLInputElement | null>(null)

const query = ref('')
type SearchState = 'idle' | 'tooShort' | 'loading' | 'done' | 'error'
const searchState = ref<SearchState>('idle')
const matches = ref<OccupationMatch[]>([])
const searchMessage = ref('')
let searchTimer: number | undefined
let searchRequestId = 0

const selectedForConfirmation = ref<Occupation | null>(null)
const isConfirming = ref(false)
const confirmError = ref('')

const voiceStatus = ref('')
const isListening = ref(false)
const isVoiceSupported = ref(true)
let recognizer: any = null
let voiceStopTimer: number | undefined

const hint = computed(() => {
  if (voiceStatus.value) return voiceStatus.value
  if (!isVoiceSupported.value) return 'Voice search is not supported in this browser. Typing works the same.'
  if (searchState.value === 'tooShort') return 'Three letters is enough to start.'
  if (searchState.value === 'loading') return 'Finding plain language matches…'
  if (searchState.value === 'error') return 'The occupation search is temporarily unavailable.'
  if (searchState.value === 'done') {
    return matches.value.length
      ? `${matches.value.length} plain language ${matches.value.length === 1 ? 'match' : 'matches'}`
      : 'No exact matches'
  }
  return 'Start typing, or tap the microphone and say it out loud.'
})

watch(query, (value) => {
  voiceStatus.value = ''
  window.clearTimeout(searchTimer)
  if (normalize(value).length < 3) {
    searchState.value = value.length ? 'tooShort' : 'idle'
    matches.value = []
    searchMessage.value = ''
    return
  }
  searchState.value = 'loading'
  searchTimer = window.setTimeout(() => runSearch(value), 260)
})

// Searches occupations by plain-language text, debounced from the query watcher below.
async function runSearch(value: string) {
  const requestId = ++searchRequestId
  try {
    const response = await fetch(`${API_BASE}/occupations/search?q=${encodeURIComponent(value)}`)
    if (!response.ok) throw new Error(`Search failed: ${response.status}`)
    const data: BackendSearchResponse = await response.json()
    if (requestId !== searchRequestId) return // a newer search started while this one was in flight
    matches.value = data.matches.map((match) => ({
      id: String(match.occupation_id),
      title: match.title,
      aliases: [],
    }))
    searchMessage.value = data.message ?? ''
    searchState.value = 'done'
  } catch {
    if (requestId !== searchRequestId) return
    matches.value = []
    searchMessage.value = 'Could not connect to the occupation search. Try again.'
    searchState.value = 'error'
  }
}

function setupVoiceSearch() {
  const SpeechRecognitionCtor = (window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition
  if (!SpeechRecognitionCtor) {
    isVoiceSupported.value = false
    return
  }
  const recognition = new SpeechRecognitionCtor()
  recognition.lang = 'en-AU'
  recognition.interimResults = false
  recognition.onstart = () => {
    isListening.value = true
    voiceStatus.value = 'Listening. Say your job.'
  }
  recognition.onresult = (event: any) => {
    const transcript = event.results[0][0].transcript.replace(/[.?!]$/, '')
    query.value = transcript
    voiceStatus.value = `Heard: "${transcript}". Change it if that is wrong.`
  }
  recognition.onerror = () => {
    voiceStatus.value = 'Did not catch that. Try again, or type it.'
  }
  recognition.onend = () => {
    isListening.value = false
    window.clearTimeout(voiceStopTimer)
  }
  recognizer = recognition
}

function toggleVoiceSearch() {
  if (!recognizer) return
  if (isListening.value) {
    recognizer.stop()
  } else {
    try {
      recognizer.start()
      window.clearTimeout(voiceStopTimer)
      voiceStopTimer = window.setTimeout(() => recognizer?.stop(), 3000)
    } catch {
      // Recognition already running or the mic was denied — ignore, the button stays usable.
    }
  }
}

function selectOccupation(occupation: Occupation) {
  selectedForConfirmation.value = occupation
  query.value = ''
  matches.value = []
  searchState.value = 'idle'
}

function changeJob() {
  selectedForConfirmation.value = null
  nextTick(() => inputEl.value?.focus())
}

// Re-fetches the occupation by id to confirm it before loading any risk data for it.
async function confirmJob() {
  if (!selectedForConfirmation.value) return
  isConfirming.value = true
  confirmError.value = ''
  try {
    const response = await fetch(`${API_BASE}/occupations/${selectedForConfirmation.value.id}`)
    if (!response.ok) throw new Error(`Occupation lookup failed: ${response.status}`)
    const data: BackendOccupationDetail = await response.json()
    confirmOccupation(String(data.id), data.title)
    router.push('/risk')
  } catch {
    confirmError.value = 'Could not confirm this occupation. Try again.'
  } finally {
    isConfirming.value = false
  }
}

onMounted(() => {
  setupVoiceSearch()
  nextTick(() => inputEl.value?.focus({ preventScroll: true }))
})
</script>

<template>
  <section id="job-finder-view" class="page-view job-finder" aria-labelledby="job-finder-title">
    <div class="wrap">
      <div class="job-finder-intro reveal-left" v-reveal>
        <p class="step-label">Start with your own words</p>
        <h2 id="job-finder-title">What do you do <em>now?</em></h2>
        <p>You do not need to know a government occupation code. Describe your work the way you would to a friend.</p>
      </div>

      <div class="selection-action reveal-scale" v-reveal style="--reveal-delay: 150ms">
        <div v-if="!selectedForConfirmation" class="search-card">
          <p class="card-eyebrow">Find your work profile</p>
          <h2>Search your occupation</h2>
          <p class="search-intro">Use your own words. No occupation code needed.</p>
          <label for="occupation-search">Your work</label>
          <div class="search-row">
            <input
              id="occupation-search"
              ref="inputEl"
              v-model="query"
              type="search"
              autocomplete="off"
              placeholder="e.g. aged care worker"
              aria-describedby="search-hint"
              aria-controls="search-results"
              data-testid="input-occupation-search"
            />
            <button
              class="mic-button"
              type="button"
              :aria-pressed="isListening"
              :disabled="!isVoiceSupported"
              aria-label="Search by voice"
              data-testid="button-voice-search"
              @click="toggleVoiceSearch"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
                <rect x="9" y="2" width="6" height="11" rx="3" />
                <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
              </svg>
            </button>
          </div>
          <div class="search-helper">
            <span id="search-hint">{{ hint }}</span>
          </div>
          <div id="search-results" class="suggestion-list" role="listbox" aria-label="Occupation matches">
            <template v-if="searchState === 'done' && matches.length">
              <p v-if="searchMessage" class="row-caption" style="margin-bottom: 10px" data-testid="status-fuzzy-match">
                {{ searchMessage }}
              </p>
              <button
                v-for="match in matches"
                :key="match.id"
                type="button"
                class="result-button"
                role="option"
                :data-testid="`option-occupation-${match.title.toLowerCase().replaceAll(' ', '-')}`"
                @click="selectOccupation(match)"
              >
                <span>
                  <span class="result-title">{{ match.title }}</span>
                  <span v-if="match.matchedAlias" class="result-alias">Matches "{{ match.matchedAlias }}"</span>
                </span>
                <span class="match-label">Match</span>
              </button>
            </template>
            <template v-else-if="searchState === 'done' && !matches.length">
              <div class="fallback-head" data-testid="status-zero-results">
                <strong>{{ searchMessage || 'No exact match. Try a different word.' }}</strong>
              </div>
            </template>
            <template v-else-if="searchState === 'error'">
              <div class="fallback-head" role="alert" data-testid="status-search-error">
                <strong>{{ searchMessage }}</strong>
              </div>
            </template>
          </div>
        </div>

        <div v-else class="confirmation-card">
          <p class="card-eyebrow">Is this your job?</p>
          <h2 data-testid="text-selected-occupation">{{ selectedForConfirmation.title }}</h2>
          <p>Every figure after this will be filtered to this occupation.</p>
          <p v-if="confirmError" class="fallback-head" data-testid="status-confirm-error"><strong>{{ confirmError }}</strong></p>
          <div class="action-row">
            <button class="outline-button" type="button" data-testid="button-change-job" @click="changeJob">Change my job</button>
            <button class="primary-button" type="button" :disabled="isConfirming" data-testid="button-confirm-job" @click="confirmJob">
              {{ isConfirming ? 'Checking…' : 'Yes, show my risk' }}
            </button>
          </div>
        </div>

        <aside class="privacy-note">
          <strong>Private by design.</strong> Risk data loads only after you confirm.
        </aside>
      </div>
    </div>
  </section>
</template>
