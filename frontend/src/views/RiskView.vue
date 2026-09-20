<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import type { BodyRegion, BodyRegionName } from '../data/types'
import { appState, resetSelection } from '../store/appState'
import { openSource } from '../store/sourceDialog'
import { API_BASE } from '../api/config'
import BodyMap from '../components/BodyMap.vue'
import Accordion from '../components/Accordion.vue'

const router = useRouter()

const occupationTitle = computed(() => appState.selectedOccupationTitle)

interface BackendBodyRegionsResponse {
  occupation_id: number
  title: string
  body_regions: BodyRegion[]
  overall_exposure_percentile: number | null
}

const bodyRegions = ref<BodyRegion[]>([])
const overallExposurePercentile = ref<number | null>(null)
const isLoadingBodyRegions = ref(false)
const bodyRegionsError = ref('')

// Fetches physical-demand exposure by body region for the selected occupation.
async function loadBodyRegions() {
  const occupationId = appState.selectedOccupationId
  bodyRegions.value = []
  overallExposurePercentile.value = null
  bodyRegionsError.value = ''
  if (!occupationId) return
  isLoadingBodyRegions.value = true
  try {
    const response = await fetch(`${API_BASE}/occupations/${occupationId}/body-regions`)
    if (!response.ok) throw new Error(`Body-regions lookup failed: ${response.status}`)
    const data: BackendBodyRegionsResponse = await response.json()
    bodyRegions.value = data.body_regions
    overallExposurePercentile.value = data.overall_exposure_percentile
  } catch {
    bodyRegionsError.value = 'Could not load this occupation’s physical demand data. Try again.'
  } finally {
    isLoadingBodyRegions.value = false
  }
}

// Ordinal suffix for the percentile stat (20 -> 20th, 21 -> 21st, 23 -> 23rd, 11-13 -> th).
function ordinal(n: number): string {
  const mod100 = n % 100
  if (mod100 >= 11 && mod100 <= 13) return `${n}th`
  const mod10 = n % 10
  if (mod10 === 1) return `${n}st`
  if (mod10 === 2) return `${n}nd`
  if (mod10 === 3) return `${n}rd`
  return `${n}th`
}

// What the percentile stat is, in plain words — a raw "20th percentile" doesn't tell most
// people what it's even measuring, let alone whether it's good or bad.
const PERCENTILE_EXPLAINER = 'Where this job ranks in physical demand among its destination jobs'

onMounted(loadBodyRegions)
watch(() => appState.selectedOccupationId, loadBodyRegions)

const activeRegionData = computed(() =>
  appState.activeRegion ? bodyRegions.value.find((r) => r.region === appState.activeRegion) : undefined,
)

const topContributors = computed(() => {
  const byVariable = new Map<string, { variable: string; score: number }>()
  bodyRegions.value.forEach((region) => {
    region.contributors.forEach((contributor) => {
      if (!byVariable.has(contributor.variable)) byVariable.set(contributor.variable, contributor)
    })
  })
  return [...byVariable.values()].sort((a, b) => b.score - a.score).slice(0, 2)
})

function selectRegion(region: BodyRegionName) {
  appState.activeRegion = region
}

function changeOccupation() {
  resetSelection()
  router.push('/check-my-job')
}

function seeDestinations() {
  router.push('/destinations')
}

function openMethodologySource() {
  // Source 3: Safe Work Australia hazard-exposure dataset.
  openSource(3)
}
</script>

<template>
  <section v-if="occupationTitle" id="risk-view" class="page-view narrow-view" aria-labelledby="risk-title">
    <div class="wrap">
      <div class="jobhead"><span class="chosen">{{ occupationTitle }}</span></div>
      <p class="step-label">Your physical demand profile</p>
      <h1 id="risk-title" style="font-size: 2rem; margin-bottom: 12px">What this work <em>asks of your body.</em></h1>
      <p class="lede" style="font-size: 1.0312rem; color: var(--slate); max-width: 62ch; margin-bottom: 12px">
        <strong>{{ occupationTitle }}</strong> — tap a part of the body to see the published hazard exposures behind it.
      </p>

      <article class="body-card" style="margin-top: 30px">
        <div class="maphead">
          <span class="lab">Physical demand by body region</span>
          <span v-if="overallExposurePercentile !== null" class="percentile-stat" data-testid="text-exposure-percentile">
            <b>{{ ordinal(overallExposurePercentile) }} percentile</b>
            <small>{{ PERCENTILE_EXPLAINER }}</small>
          </span>
        </div>

        <p v-if="isLoadingBodyRegions" class="floor-rule">Loading…</p>
        <p v-else-if="bodyRegionsError" class="floor-rule" data-testid="status-body-regions-error">{{ bodyRegionsError }}</p>

        <template v-else>
          <BodyMap :active-region="appState.activeRegion" :regions="bodyRegions" @select="selectRegion">
            <template #detail>
              <div aria-live="polite">
                <p v-if="!appState.activeRegion" class="prompt">
                  <b>Pick a part of the body</b>Tap the map, or choose from the list, to see the leading published
                  hazard exposures recorded for that region.
                </p>
                <div v-else-if="activeRegionData && activeRegionData.score !== null" class="mechanism-content">
                  <div class="mechanism-head">
                    <div>
                      <p class="card-eyebrow">Selected region</p>
                      <h2 data-testid="text-active-region">{{ activeRegionData.region }}</h2>
                    </div>
                    <div class="proportion" data-testid="text-region-score">
                      {{ Math.round(activeRegionData.score) }}/100<small>rounded physical demand score</small>
                    </div>
                  </div>
                  <p class="mlab">Leading published hazard exposures</p>
                  <div class="mechanism-list">
                    <div
                      v-for="(contributor, index) in activeRegionData.contributors"
                      :key="contributor.variable"
                      class="mechanism-row"
                      :data-testid="`row-mechanism-${index + 1}`"
                    >
                      <div class="mechanism-line">
                        <span class="mechanism-name">{{ contributor.variable }}</span>
                        <span class="mechanism-value">{{ Math.round(contributor.score) }}</span>
                      </div>
                      <div class="mech-bar"><i :style="{ width: contributor.score + '%' }"></i></div>
                    </div>
                  </div>
                  <p class="srcnote"><span class="src-dot"></span>See how these figures are calculated below.</p>
                </div>
                <div v-else class="floor-state" data-testid="status-no-published-figure">
                  <p class="card-eyebrow">{{ activeRegionData?.region }}</p>
                  <h2>No published figure</h2>
                  <p>{{ activeRegionData?.message ?? 'There is no published hazard-exposure measure for this body region and occupation.' }}</p>
                </div>
              </div>
            </template>
            <template #note>
              <aside v-if="appState.activeRegion" class="data-note">
                <strong>What the numbers mean.</strong> Each region carries a demand score out of 100. It is how much
                this job loads that part of the body, measured from published hazard exposure. A higher number means
                the work asks more of that region than of the others. It is not a chance of being injured.
              </aside>
            </template>
          </BodyMap>

          <div class="scale">
            <span>Lower exposure</span>
            <span style="display: flex; gap: 3px">
              <span class="sw" style="background: var(--r1)"></span>
              <span class="sw" style="background: var(--r2)"></span>
              <span class="sw" style="background: var(--r3)"></span>
              <span class="sw" style="background: var(--r4)"></span>
            </span>
            <span>Higher exposure</span>
          </div>
          <p class="scale-note">Parts with no published figure are shown pale and carry no number.</p>
        </template>
      </article>

      <div class="accordion-stack">
        <Accordion title="Where physical demand comes from" testid="button-accordion-mechanisms">
          <p class="row-caption" style="margin-bottom: 10px">The two highest-scoring hazard exposures across every body region for this occupation:</p>
          <p v-for="contributor in topContributors" :key="contributor.variable">
            <strong>{{ contributor.variable }}.</strong> Rounded score {{ Math.round(contributor.score) }}
          </p>
        </Accordion>
      </div>

      <button class="srcbtn" type="button" data-testid="button-source" @click="openMethodologySource">How this is calculated</button>

      <aside class="data-note">
        <strong>Read this carefully.</strong> These figures describe published hazard exposure, not your personal
        chance of injury. The Safe Work Australia Occupational Hazards Dataset is a beta release derived by mapping
        United States occupational data onto Australian occupations.
      </aside>

      <div class="action-row risk-actions">
        <button class="cta-g cta" type="button" data-testid="button-profile-change-job" @click="changeOccupation">
          <svg viewBox="0 0 24 24" aria-hidden="true" width="16" height="16"><path d="m15 18-6-6 6-6" fill="none" stroke="currentColor" stroke-width="2" /></svg>
          Change occupation
        </button>
        <button class="primary-button" type="button" data-testid="button-see-destinations" @click="seeDestinations">
          See where people went
        </button>
      </div>
    </div>
  </section>
</template>
