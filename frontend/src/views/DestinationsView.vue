<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { appState, resetSelection } from '../store/appState'
import { openSource } from '../store/sourceDialog'
import { API_BASE } from '../api/config'
import SourceStatButton from '../components/SourceStatButton.vue'
import DestinationCard from '../components/DestinationCard.vue'
import DetailSection from '../components/DetailSection.vue'
import type { BodyRegion, BodyRegionName, Destination } from '../data/types'

const router = useRouter()

const occupationTitle = computed(() => appState.selectedOccupationTitle)

interface BackendDestination {
  occupation_id: number
  title: string
  share: number
  source_id: number
  tag: string
  body_load_band: 'up' | 'down' | 'same' | null
  region_share_percentage: number | null
  tier: 'Lower than typical' | 'About typical' | 'Higher than typical' | null
}

interface BackendDestinationsResponse {
  occupation_id: number
  is_fallback: boolean
  group: string | null
  destinations: BackendDestination[]
}

// Published JSA Generative AI Capacity Study ratings — real, not modelled by us.
// 0-1 scale. `message` is a permanent caveat that must travel with the number
// whenever it's shown (AC7.1), not just a fallback for the missing-data case.
interface BackendAiExposure {
  automation_exposure: number | null
  message: string | null
}

// Published at 6-digit ANZSCO, one level finer than our 4-digit occupations —
// one occupation can have several specialisations with genuinely different
// gender pay gaps (see backend's own README), so this is never averaged down
// to one number.
interface BackendPayGapSpecialization {
  gender_pay_gap: number | null
}

interface BackendPayGap {
  specializations: BackendPayGapSpecialization[]
}

// From occupation_profile (JSA), joined onto GET /occupations/{id} — null for the 43
// occupations with no JSA profile, never a fabricated placeholder.
interface BackendOccupationProfile {
  median_weekly_earnings: number | null
  part_time_share_pct: number | null
  female_share_pct: number | null
}

// GET /occupations/{id}/injury-insight — the standalone, single-occupation counterpart to the
// tier already attached to each destination in the /destinations list. This is what fills
// "Your job now" for the injury comparison, since the destinations endpoint only ever scores
// destinations relative to a source occupation, never the source occupation itself.
// insight is null (with message explaining why) when there isn't enough data to estimate it.
interface BackendInjuryInsight {
  occupation_id: number
  title: string
  insight: {
    tier: 'Lower than typical' | 'About typical' | 'Higher than typical'
    model_name: string
    model_version: string
    generated_at: string
  } | null
  message: string | null
}

// The destinations endpoint itself has no tasks field — a destination's tasks live on
// the occupation entity (GET /occupations/{id}), fetched separately in openDestination
// below, since a destination's occupation_id is just an ordinary occupation id.
function toDestination(d: BackendDestination): Destination {
  return {
    id: d.occupation_id,
    title: d.title,
    share: d.share,
    tag: d.tag,
    sourceId: d.source_id,
    tasks: [],
    bodyLoadBand: d.body_load_band,
    regionSharePercentage: d.region_share_percentage,
    tier: d.tier,
  }
}

const destinations = ref<Destination[]>([])
const isFallbackGroup = ref(false)
const fallbackGroupName = ref<string | null>(null)
const isLoading = ref(false)

interface BackendBodyRegionsResponse {
  occupation_id: number
  title: string
  body_regions: BodyRegion[]
}

// Body-region breakdowns, keyed by occupation id — only ever holds at most two entries: the
// confirmed occupation's own (fetched once per occupation below) and the currently open
// destination's (fetched in openDestination). Sorting/filtering the destinations list by body
// load now happens server-side (body_load_band on each destination), so this map only powers
// the detail panel's own region-by-region comparison chart, not the list.
const bodyRegionsByDestination = ref<Map<number, BodyRegion[]>>(new Map())

async function loadCurrentOccupationBodyRegions(occupationId: string) {
  try {
    const response = await fetch(`${API_BASE}/occupations/${occupationId}/body-regions`)
    if (!response.ok) return
    const data: BackendBodyRegionsResponse = await response.json()
    bodyRegionsByDestination.value = new Map(bodyRegionsByDestination.value).set(Number(occupationId), data.body_regions)
  } catch {
    // leave unset — the detail panel's region comparison just won't render rows
  }
}

// Fetches ranked destination occupations for the selected occupation.
// The confirmed occupation's own pay gap — fetched once per occupation, not per destination,
// so the "Gender pay gap" row can show "your job now" next to "this job" like the body-cost
// and injury-frequency comparisons already do.
const currentOccupationPayGap = ref<BackendPayGap | null>(null)
async function loadCurrentOccupationPayGap(occupationId: string) {
  currentOccupationPayGap.value = null
  try {
    const response = await fetch(`${API_BASE}/occupations/${occupationId}/pay-gap`)
    if (response.ok) currentOccupationPayGap.value = await response.json()
  } catch {
    // leave null — the row just shows "Not published for this occupation"
  }
}

// The confirmed occupation's own median pay / part-time share / women's share — fetched
// once per occupation, same reason as loadCurrentOccupationPayGap above.
const currentOccupationProfile = ref<BackendOccupationProfile | null>(null)
async function loadCurrentOccupationProfile(occupationId: string) {
  currentOccupationProfile.value = null
  try {
    const response = await fetch(`${API_BASE}/occupations/${occupationId}`)
    if (response.ok) currentOccupationProfile.value = await response.json()
  } catch {
    // leave null — the row just shows "Not published"
  }
}

// The confirmed occupation's own automation exposure — for the "Compare with my job" module's
// Automation exposure row, same reason as the two loaders above.
const currentOccupationAiExposure = ref<BackendAiExposure | null>(null)
async function loadCurrentOccupationAiExposure(occupationId: string) {
  currentOccupationAiExposure.value = null
  try {
    const response = await fetch(`${API_BASE}/occupations/${occupationId}/ai-exposure`)
    if (response.ok) currentOccupationAiExposure.value = await response.json()
  } catch {
    // leave null — the row just shows "Not published"
  }
}

// The confirmed occupation's own injury-risk tier — for the "Injury frequency signal" row's
// "Your job now" side. The destination's own tier is already on the /destinations list
// response (BackendDestination.tier), so this is only needed for the source occupation.
const currentOccupationInjuryInsight = ref<BackendInjuryInsight | null>(null)
async function loadCurrentOccupationInjuryInsight(occupationId: string) {
  currentOccupationInjuryInsight.value = null
  try {
    const response = await fetch(`${API_BASE}/occupations/${occupationId}/injury-insight`)
    if (response.ok) currentOccupationInjuryInsight.value = await response.json()
  } catch {
    // leave null — the row just shows "Not published yet"
  }
}

// Builds the query string for the current sort/compare/showHarderMoves/region selections —
// Iteration 2's server-side filters (Wenlu's API_REQUIREMENTS.md), shipped by the backend
// 2026-09-17. compareRegion is only meaningful (and only sent) for best_relief.
function buildDestinationsQuery(): string {
  const params = new URLSearchParams()
  params.set('sort', SORT_PARAM[sortOption.value])
  if (sortOption.value === 'best-relief-picked' && compareOption.value !== 'overall') {
    params.set('compareRegion', compareOption.value)
  }
  params.set('showHarderMoves', String(showHarderMoves.value))
  if (selectedStates.value.size) params.set('states', [...selectedStates.value].join(','))
  if (selectedSa4Regions.value.size) params.set('sa4Regions', [...selectedSa4Regions.value].join(','))
  return params.toString()
}

// Re-fetches just the destinations list with the current filters — cheap enough to call on
// every sort/filter change, unlike loadDestinations below which also reloads the confirmed
// occupation's own profile/pay-gap/body-regions (those don't change when a filter does).
async function loadDestinationsList() {
  const occupationId = appState.selectedOccupationId
  if (!occupationId) {
    destinations.value = []
    isFallbackGroup.value = false
    fallbackGroupName.value = null
    return
  }
  isLoading.value = true
  try {
    const response = await fetch(`${API_BASE}/occupations/${occupationId}/destinations?${buildDestinationsQuery()}`)
    if (!response.ok) throw new Error(`Destinations lookup failed: ${response.status}`)
    const data: BackendDestinationsResponse = await response.json()
    isFallbackGroup.value = data.is_fallback
    fallbackGroupName.value = data.group
    destinations.value = data.destinations.map(toDestination)
  } catch {
    destinations.value = []
  } finally {
    isLoading.value = false
  }
}

async function loadDestinations() {
  const occupationId = appState.selectedOccupationId
  bodyRegionsByDestination.value = new Map()
  if (!occupationId) {
    destinations.value = []
    isFallbackGroup.value = false
    fallbackGroupName.value = null
    return
  }
  loadCurrentOccupationPayGap(occupationId) // not awaited, same as the four below
  loadCurrentOccupationProfile(occupationId)
  loadCurrentOccupationAiExposure(occupationId)
  loadCurrentOccupationInjuryInsight(occupationId)
  loadCurrentOccupationBodyRegions(occupationId)
  await loadDestinationsList()
}

onMounted(loadDestinations)
watch(() => appState.selectedOccupationId, loadDestinations)

onMounted(() => window.addEventListener('keydown', onDetailKeydown))
onUnmounted(() => window.removeEventListener('keydown', onDetailKeydown))

const isFiltersOpen = ref(false)

// Location filter is functionally correct but hidden pending a redesign — Shiza asked to hide
// it since its effect is too subtle for most occupations to be worth shipping as-is. Flip back
// to true once the redesigned version is ready; the underlying state/query-param logic is untouched.
const SHOW_LOCATION_FILTER = false

// Real ABS state and Victorian SA4 region names, matching the states/sa4Regions query params
// the backend's destinations endpoint takes 1:1 (shipped 2026-09-17 — see
// occupation_profile.md / the backend's _SA4_SLUG_TO_CODE map for the exact slugs).
const AUSTRALIAN_STATES: { code: string; name: string }[] = [
  { code: 'VIC', name: 'Victoria' },
  { code: 'NSW', name: 'New South Wales' },
  { code: 'QLD', name: 'Queensland' },
  { code: 'WA', name: 'Western Australia' },
  { code: 'SA', name: 'South Australia' },
  { code: 'TAS', name: 'Tasmania' },
  { code: 'ACT', name: 'Aust. Capital Territory' },
  { code: 'NT', name: 'Northern Territory' },
]
const VIC_SA4_REGIONS: { code: string; name: string }[] = [
  { code: 'mel-inner', name: 'Melbourne, Inner' },
  { code: 'mel-inner-east', name: 'Melbourne, Inner East' },
  { code: 'mel-inner-south', name: 'Melbourne, Inner South' },
  { code: 'mel-north-east', name: 'Melbourne, North East' },
  { code: 'mel-north-west', name: 'Melbourne, North West' },
  { code: 'mel-outer-east', name: 'Melbourne, Outer East' },
  { code: 'mel-south-east', name: 'Melbourne, South East' },
  { code: 'mel-west', name: 'Melbourne, West' },
  { code: 'mornington', name: 'Mornington Peninsula' },
  { code: 'ballarat', name: 'Ballarat' },
  { code: 'bendigo', name: 'Bendigo' },
  { code: 'geelong', name: 'Geelong' },
  { code: 'hume', name: 'Hume' },
  { code: 'latrobe', name: 'Latrobe, Gippsland' },
  { code: 'nw-vic', name: 'North West' },
  { code: 'shepparton', name: 'Shepparton' },
  { code: 'warrnambool', name: 'Warrnambool and South West' },
]

type SortOption =
  | 'most-common-move'
  | 'kindest-overall'
  | 'best-relief-picked'
  | 'highest-pay'
  | 'most-part-time'
  | 'most-women'
  | 'least-automation'
  | 'a-to-z'
const sortOption = ref<SortOption>('most-common-move')

// Maps the frontend's own option values (unchanged, so nothing else in this file has to
// change) to the backend's `sort` query param names.
const SORT_PARAM: Record<SortOption, string> = {
  'most-common-move': 'most_common',
  'kindest-overall': 'kindest_overall',
  'best-relief-picked': 'best_relief',
  'highest-pay': 'highest_pay',
  'most-part-time': 'most_part_time',
  'most-women': 'most_women',
  'least-automation': 'least_automation',
  'a-to-z': 'a_to_z',
}

type CompareOption = 'overall' | BodyRegionName
const compareOption = ref<CompareOption>('overall')

// Picking what to compare switches the sort to match it — that's the whole point of picking
// a part. "Overall load" counts as a part too (it means "your whole body"), not a null state.
// Suppressed during clearAllFilters below, which sets compareOption back to 'overall' as part
// of a full reset and needs sortOption to land on 'most-common-move', not this.
let suppressCompareWatch = false
watch(compareOption, () => {
  if (!suppressCompareWatch) sortOption.value = 'best-relief-picked'
})

const comparePartLabel = computed(() => (compareOption.value === 'overall' ? 'whole body' : compareOption.value.toLowerCase()))

const sortDescription = computed(() => {
  if (sortOption.value === 'kindest-overall') return 'kindest to your body first'
  if (sortOption.value === 'best-relief-picked') return `best relief for your ${comparePartLabel.value} first`
  if (sortOption.value === 'highest-pay') return 'highest pay first'
  if (sortOption.value === 'most-part-time') return 'most part-time roles first'
  if (sortOption.value === 'most-women') return 'most women in the role first'
  if (sortOption.value === 'least-automation') return 'least exposed to automation first'
  if (sortOption.value === 'a-to-z') return 'A to Z'
  return 'most common move first'
})

// Longer form for the detail panel's own badge — DestinationCard.vue has its own short form
// for the list-row chip, matching the same 'down'/'up'/'same' band value passed into it. The
// band itself comes straight from the backend (body_load_band, same ±8 tolerance this used to
// compute client-side) rather than being computed here.
type LoadBand = 'down' | 'up' | 'same' | null
const detailLoadBandLabel: Record<Exclude<LoadBand, null>, string> = {
  down: 'Takes load off your body',
  up: 'Adds load to your body',
  same: 'About the same on your body',
}

// The injury-tier model's three labels, reusing the same down/up/same vocabulary and
// .band-badge styling as the body-load badge above — down/lower is good, up/higher is bad.
// A rough estimate from a model trained on physical-demand data, not a published injury
// count; null when there isn't enough data to estimate it.
const TIER_BAND: Record<string, Exclude<LoadBand, null>> = {
  'Lower than typical': 'down',
  'About typical': 'same',
  'Higher than typical': 'up',
}
function tierBand(tier: string | null | undefined): LoadBand {
  return tier ? (TIER_BAND[tier] ?? null) : null
}

// Defaults to showing everything — off, it hides only destinations the backend can confirm
// are equal or higher overall body load than the confirmed occupation (showHarderMoves query
// param). Unscored destinations stay visible either way.
const showHarderMoves = ref(true)

// Selecting an SA4 region implies Victoria, same as the filter panel's own caption already
// promised before these checkboxes were wired to anything real.
const selectedStates = ref<Set<string>>(new Set())
const selectedSa4Regions = ref<Set<string>>(new Set())
function toggleState(code: string) {
  const next = new Set(selectedStates.value)
  if (next.has(code)) next.delete(code)
  else next.add(code)
  selectedStates.value = next
}
function toggleSa4Region(code: string) {
  const next = new Set(selectedSa4Regions.value)
  if (next.has(code)) next.delete(code)
  else next.add(code)
  selectedSa4Regions.value = next
  if (next.size > 0 && !selectedStates.value.has('VIC')) toggleState('VIC')
}
function selectAllStates() {
  selectedStates.value = new Set(AUSTRALIAN_STATES.map((s) => s.code))
}
function clearStates() {
  selectedStates.value = new Set()
}
function selectAllSa4Regions() {
  selectedSa4Regions.value = new Set(VIC_SA4_REGIONS.map((s) => s.code))
  if (!selectedStates.value.has('VIC')) toggleState('VIC')
}
function clearSa4Regions() {
  selectedSa4Regions.value = new Set()
}

function clearAllFilters() {
  suppressCompareWatch = true
  sortOption.value = 'most-common-move'
  compareOption.value = 'overall'
  showHarderMoves.value = true
  selectedStates.value = new Set()
  selectedSa4Regions.value = new Set()
  isFiltersOpen.value = false
  nextTick(() => {
    suppressCompareWatch = false
  })
}

function sortChipLabel(option: SortOption): string {
  if (option === 'kindest-overall') return 'Kindest overall'
  if (option === 'highest-pay') return 'Highest pay'
  if (option === 'most-part-time') return 'Most part-time'
  if (option === 'most-women') return 'Most women in role'
  if (option === 'least-automation') return 'Least automation'
  if (option === 'a-to-z') return 'A to Z'
  return ''
}

// Pills shown next to the Filters button once something's picked, each removable on its own.
// 'best-relief-picked' folds sort+compare into one chip since picking a compare part is what
// drives that sort — showing two chips for one choice would be confusing.
const activeFilterChips = computed(() => {
  const chips: { key: string; label: string; clear: () => void }[] = []
  if (sortOption.value === 'best-relief-picked') {
    chips.push({
      key: 'sort',
      label: `Best relief: ${comparePartLabel.value}`,
      clear: () => {
        suppressCompareWatch = true
        sortOption.value = 'most-common-move'
        compareOption.value = 'overall'
        nextTick(() => {
          suppressCompareWatch = false
        })
      },
    })
  } else if (sortOption.value !== 'most-common-move') {
    chips.push({ key: 'sort', label: sortChipLabel(sortOption.value), clear: () => { sortOption.value = 'most-common-move' } })
  }
  if (!showHarderMoves.value) {
    chips.push({ key: 'harder', label: 'Harder moves hidden', clear: () => { showHarderMoves.value = true } })
  }
  const regionCount = selectedStates.value.size + selectedSa4Regions.value.size
  if (regionCount > 0) {
    chips.push({
      key: 'region',
      label: `Region: ${regionCount} selected`,
      clear: () => {
        selectedStates.value = new Set()
        selectedSa4Regions.value = new Set()
      },
    })
  }
  return chips
})

watch([sortOption, compareOption, showHarderMoves, selectedStates, selectedSa4Regions], loadDestinationsList)

const selectedIndex = ref<number | null>(null)
const selectedDestination = ref<Destination | null>(null)
const isDetailExpanded = ref(false)
const isDetailLoading = ref(false)
const destinationAiExposure = ref<BackendAiExposure | null>(null)
const destinationPayGap = ref<BackendPayGap | null>(null)
const destinationProfile = ref<BackendOccupationProfile | null>(null)

// Never averaged down to one number — see the BackendPayGap comment above. Shows a single
// figure when the occupation has one specialisation, a range when it has several.
function formatGenderPayGap(payGap: BackendPayGap | null): string | null {
  const gaps = (payGap?.specializations ?? []).map((s) => s.gender_pay_gap).filter((g): g is number => g !== null)
  if (!gaps.length) return null
  const fmt = (n: number) => `${(n * 100).toFixed(1)}%`
  const min = Math.min(...gaps)
  const max = Math.max(...gaps)
  return min === max ? fmt(min) : `${fmt(min)}–${fmt(max)}`
}

const genderPayGapText = computed(() => formatGenderPayGap(destinationPayGap.value))
const currentGenderPayGapText = computed(() => formatGenderPayGap(currentOccupationPayGap.value))

// AC4.2: label the direction of change, not just show two numbers. Only when both sides
// resolve to exactly one specialisation each — with a range on either side there's no single
// pair of numbers to call "better" or "worse" without picking one arbitrarily.
type CompareDirection = 'better' | 'worse' | 'same'
const payGapComparison = computed<{ direction: CompareDirection; note: string } | null>(() => {
  const currentGaps = (currentOccupationPayGap.value?.specializations ?? [])
    .map((s) => s.gender_pay_gap)
    .filter((g): g is number => g !== null)
  const destGaps = (destinationPayGap.value?.specializations ?? [])
    .map((s) => s.gender_pay_gap)
    .filter((g): g is number => g !== null)
  const [currentGap] = currentGaps
  const [destGap] = destGaps
  if (currentGap === undefined || destGap === undefined || currentGaps.length !== 1 || destGaps.length !== 1) return null
  const diffPp = (currentGap - destGap) * 100 // positive = this job's gap is smaller
  if (Math.abs(diffPp) < 0.5) return { direction: 'same', note: 'About the same' }
  return {
    direction: diffPp > 0 ? 'better' : 'worse',
    note: `${Math.abs(diffPp).toFixed(1)}pp ${diffPp > 0 ? 'smaller' : 'larger'} gap`,
  }
})

function formatSharePct(value: number | null | undefined): string | null {
  return value == null ? null : `${value.toFixed(1)}%`
}
const currentWomenShareText = computed(() => formatSharePct(currentOccupationProfile.value?.female_share_pct))
const destWomenShareText = computed(() => formatSharePct(destinationProfile.value?.female_share_pct))

function formatDollars(value: number | null | undefined): string | null {
  return value == null ? null : `$${Math.round(value)}`
}
const currentPayText = computed(() => formatDollars(currentOccupationProfile.value?.median_weekly_earnings))
const destPayText = computed(() => formatDollars(destinationProfile.value?.median_weekly_earnings))

function formatWholePct(value: number | null | undefined): string | null {
  return value == null ? null : `${Math.round(value)}%`
}
const currentPartTimeText = computed(() => formatWholePct(currentOccupationProfile.value?.part_time_share_pct))
const destPartTimeText = computed(() => formatWholePct(destinationProfile.value?.part_time_share_pct))

function formatAutomationScore(value: number | null | undefined): string | null {
  return value == null ? null : `${Math.round(value * 100)}/100`
}
const currentAutomationText = computed(() => formatAutomationScore(currentOccupationAiExposure.value?.automation_exposure))
const destAutomationText = computed(() => formatAutomationScore(destinationAiExposure.value?.automation_exposure))

// AC4.2 scoped this row to the same Better/Worse/Same treatment as gender pay gap. Product
// decision (Way Out is aimed at women): a higher women's share is Better — a more
// female-dominated destination, not a closeness-to-current-job comparison.
const womenInRoleComparison = computed<{ direction: CompareDirection; note: string } | null>(() => {
  const current = currentOccupationProfile.value?.female_share_pct
  const dest = destinationProfile.value?.female_share_pct
  if (current == null || dest == null) return null
  const diffPp = dest - current // positive = this job has more women
  if (Math.abs(diffPp) < 3) return { direction: 'same', note: 'About the same' }
  return {
    direction: diffPp > 0 ? 'better' : 'worse',
    note: `${Math.abs(diffPp).toFixed(1)}pp ${diffPp > 0 ? 'more' : 'fewer'} women`,
  }
})

// Higher pay is unambiguously Better — unlike women-in-role, no direction judgment call here.
const medianPayComparison = computed<{ direction: CompareDirection; note: string } | null>(() => {
  const current = currentOccupationProfile.value?.median_weekly_earnings
  const dest = destinationProfile.value?.median_weekly_earnings
  if (current == null || dest == null) return null
  const diff = Math.round(dest - current)
  if (Math.abs(diff) < 20) return { direction: 'same', note: 'About the same' }
  return { direction: diff > 0 ? 'better' : 'worse', note: `${diff > 0 ? '+' : '−'}$${Math.abs(diff)} per week` }
})

// More part-time availability is Better — this product's whole premise is finding work that
// fits around physical limits, and part-time is the clearest lever for that.
const partTimeComparison = computed<{ direction: CompareDirection; note: string } | null>(() => {
  const current = currentOccupationProfile.value?.part_time_share_pct
  const dest = destinationProfile.value?.part_time_share_pct
  if (current == null || dest == null) return null
  const diffPp = dest - current
  if (Math.abs(diffPp) < 3) return { direction: 'same', note: 'About the same' }
  return {
    direction: diffPp > 0 ? 'better' : 'worse',
    note: diffPp > 0 ? 'More part-time options' : 'Fewer part-time options',
  }
})

// Lower automation exposure is Better — less risk of the role itself disappearing.
const automationComparison = computed<{ direction: CompareDirection; note: string } | null>(() => {
  const current = currentOccupationAiExposure.value?.automation_exposure
  const dest = destinationAiExposure.value?.automation_exposure
  if (current == null || dest == null) return null
  const diffPct = Math.round((dest - current) * 100)
  if (Math.abs(diffPct) < 3) return { direction: 'same', note: 'About the same' }
  return {
    direction: diffPct < 0 ? 'better' : 'worse',
    note: diffPct < 0 ? 'Lower automation risk' : 'Higher automation risk',
  }
})

// Fetches detail for one destination once its card is opened: its description, tasks, and
// occupation_profile fields (pay/part-time/women's share) from the occupation entity endpoint
// (a destination's occupation_id is just an ordinary occupation id), plus the two separate
// per-occupation endpoints (AI exposure, gender pay gap). Entry requirement and injury
// frequency still have no backend field to call.
async function openDestination(index: number) {
  selectedIndex.value = index
  isDetailExpanded.value = false
  const summary = destinations.value[index]
  const occupationId = appState.selectedOccupationId
  if (!summary || !occupationId) return
  selectedDestination.value = summary // show what we already have while the detail loads
  isDetailLoading.value = true
  destinationAiExposure.value = null
  destinationPayGap.value = null
  destinationProfile.value = null
  try {
    const [detailResponse, occupationResponse, aiExposureResponse, payGapResponse, bodyRegionsResponse] = await Promise.all([
      fetch(`${API_BASE}/occupations/${occupationId}/destinations/${summary.id}`),
      fetch(`${API_BASE}/occupations/${summary.id}`),
      fetch(`${API_BASE}/occupations/${summary.id}/ai-exposure`),
      fetch(`${API_BASE}/occupations/${summary.id}/pay-gap`),
      fetch(`${API_BASE}/occupations/${summary.id}/body-regions`),
    ])
    if (selectedIndex.value !== index) return
    let next = selectedDestination.value
    if (detailResponse.ok) {
      const data: BackendDestination = await detailResponse.json()
      // The single-destination detail endpoint has no tag, body_load_band,
      // region_share_percentage, or tier fields at all (different response shape from the
      // list) — keep those from the list-derived summary rather than letting toDestination's
      // undefined-field mapping clobber them.
      next = {
        ...toDestination(data),
        tag: summary.tag,
        bodyLoadBand: summary.bodyLoadBand,
        regionSharePercentage: summary.regionSharePercentage,
        tier: summary.tier,
      }
    }
    if (occupationResponse.ok) {
      const occupation: { tasks: string[]; description: string | null } & BackendOccupationProfile =
        await occupationResponse.json()
      next = { ...next, tasks: occupation.tasks, description: occupation.description }
      destinationProfile.value = occupation
    }
    selectedDestination.value = next
    if (aiExposureResponse.ok) destinationAiExposure.value = await aiExposureResponse.json()
    if (payGapResponse.ok) destinationPayGap.value = await payGapResponse.json()
    if (bodyRegionsResponse.ok) {
      const data: BackendBodyRegionsResponse = await bodyRegionsResponse.json()
      bodyRegionsByDestination.value = new Map(bodyRegionsByDestination.value).set(summary.id, data.body_regions)
    }
  } catch {
    // keep showing the list-derived summary — better than an error for a figure we already have
  } finally {
    if (selectedIndex.value === index) isDetailLoading.value = false
  }
}

function closeDestination() {
  selectedIndex.value = null
  selectedDestination.value = null
  isDetailExpanded.value = false
  isDetailLoading.value = false
}

const BODY_REGION_NAMES: BodyRegionName[] = [
  'Lower back',
  'Shoulders and upper arms',
  'Hands and wrists',
  'Knees',
  'Legs and feet',
  'Whole body and fall risk',
]

interface RegionComparisonRow {
  region: BodyRegionName
  now: number | null
  next: number | null
  diff: number | null
}

// "now" is the confirmed occupation's score for that region, "next" is the open destination's
// — both come from the same body-regions fetch used for sorting, just read per-region here.
const detailRegionComparison = computed<RegionComparisonRow[]>(() => {
  const destination = selectedDestination.value
  const occupationId = appState.selectedOccupationId
  if (!destination || !occupationId) return []
  const nowRegions = bodyRegionsByDestination.value.get(Number(occupationId))
  const nextRegions = bodyRegionsByDestination.value.get(destination.id)
  if (!nowRegions || !nextRegions) return []
  return BODY_REGION_NAMES.map((region) => {
    const now = nowRegions.find((r) => r.region === region)?.score ?? null
    const next = nextRegions.find((r) => r.region === region)?.score ?? null
    return { region, now, next, diff: now !== null && next !== null ? next - now : null }
  })
})

const detailLoadBand = computed<LoadBand>(() => selectedDestination.value?.bodyLoadBand ?? null)

// The region picked in Compare if there is one, otherwise the 4 regions whose scores moved
// the most either way — matches what "best relief for the part I picked" is already sorting by.
const detailFocusRegions = computed(() => {
  const rows = detailRegionComparison.value.filter((r): r is RegionComparisonRow & { diff: number } => r.diff !== null)
  if (compareOption.value !== 'overall') return rows.filter((r) => r.region === compareOption.value)
  return [...rows].sort((a, b) => Math.abs(b.diff) - Math.abs(a.diff)).slice(0, 4)
})

function joinWithAnd(items: string[]): string {
  if (items.length <= 1) return items.join('')
  if (items.length === 2) return items.join(' and ')
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}

const detailTradeText = computed(() => {
  const rows = detailRegionComparison.value.filter((r): r is RegionComparisonRow & { diff: number } => r.diff !== null)
  const easier = rows.filter((r) => r.diff <= -12).sort((a, b) => a.diff - b.diff)
  const harder = rows.filter((r) => r.diff >= 8).sort((a, b) => b.diff - a.diff)
  const parts: string[] = []
  if (easier.length) parts.push(`Easier on your ${joinWithAnd(easier.slice(0, 3).map((r) => r.region.toLowerCase()))}.`)
  if (harder.length) parts.push(`Harder on your ${joinWithAnd(harder.slice(0, 2).map((r) => r.region.toLowerCase()))}.`)
  return parts.length ? parts.join(' ') : 'Much the same across your body as the job you are in now.'
})

function toggleDestinationExpanded() {
  isDetailExpanded.value = !isDetailExpanded.value
}

function onDetailKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && isDetailExpanded.value) toggleDestinationExpanded()
}

function backToRisk() {
  router.push('/risk')
}

function startAgain() {
  resetSelection()
  router.push('/check-my-job')
}

function openMobilitySource() {
  // Every row shares one source_id for this dataset; 4 is just a fallback for
  // before anything has loaded.
  openSource(destinations.value[0]?.sourceId ?? 4)
}

function openBodyScoresSource() {
  // Same body-regions methodology source RiskView cites — source id 3, BOHD.
  openSource(3, 'the physical demand scores for this occupation')
}
</script>

<template>
  <section v-if="occupationTitle" id="destinations-view" class="page-view narrow-view"
    aria-labelledby="destinations-title">
    <div class="wrap">
      <div class="jobhead"><span class="chosen">{{ occupationTitle }}</span></div>
      <p class="step-label">Your next chapter</p>
      <h1 id="destinations-title" style="font-size: 2.5rem; margin-bottom: 12px">Where people <em>went.</em></h1>
      <p class="lede" style="margin-bottom: 24px">
        Every row is a move people actually made out of {{ occupationTitle }}. Open one to see what it would cost
        your body, and what else changes.
      </p>

      <p v-if="isLoading" class="floor-rule">Loading…</p>

      <div v-if="isFallbackGroup" class="fallback-banner" data-testid="status-mobility-fallback"
        style="margin-bottom: 24px">
        <p class="card-eyebrow">Nearest published group</p>
        <h2>No transition data is published for this occupation</h2>
        <p>We are showing the nearest occupation group instead. Group results are broader and may include work unlike
          your exact role.</p>
        <strong>{{ fallbackGroupName }}</strong>
      </div>

      <p v-if="SHOW_LOCATION_FILTER" class="row-caption" style="margin-bottom: 14px">
        Showing work <b>anywhere in Australia</b>. Use Filters to narrow to your state or region.
      </p>

      <div class="destination-filters-bar">
        <button class="fbtn" type="button" :aria-expanded="isFiltersOpen" aria-controls="destination-filter-panel"
          data-testid="button-open-filters" @click="isFiltersOpen = !isFiltersOpen">
          <svg viewBox="0 0 24 24" aria-hidden="true" width="16" height="16" fill="none" stroke="currentColor"
            stroke-width="2" stroke-linecap="round">
            <path d="M4 6h16M7 12h10M10 18h4" />
          </svg>
          Filters
          <span v-if="activeFilterChips.length" class="fbtn-badge">{{ activeFilterChips.length }}</span>
        </button>
        <span v-for="chip in activeFilterChips" :key="chip.key" class="filter-chip">
          {{ chip.label }}
          <button type="button" class="filter-chip-x" :aria-label="`Remove ${chip.label} filter`" @click="chip.clear">
            <svg viewBox="0 0 24 24" aria-hidden="true" width="12" height="12" fill="none" stroke="currentColor"
              stroke-width="2.5" stroke-linecap="round">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </span>
        <button v-if="activeFilterChips.length" type="button" class="clear-all-link"
          data-testid="button-clear-all-inline" @click="clearAllFilters">
          <svg viewBox="0 0 24 24" aria-hidden="true" width="12" height="12" fill="none" stroke="currentColor"
            stroke-width="2.5" stroke-linecap="round">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
          Clear all
        </button>
      </div>

      <div v-if="isFiltersOpen" id="destination-filter-panel" class="destination-filters">
        <div class="filter-col">
          <div class="filter-field">
            <label for="destination-sort">Order these by</label>
            <select id="destination-sort" v-model="sortOption" data-testid="select-destination-sort">
              <optgroup label="What most people did">
                <option value="most-common-move">Most common move</option>
              </optgroup>
              <optgroup label="Your body">
                <option value="kindest-overall">Kindest to my body overall</option>
                <option value="best-relief-picked">Best relief for the part I picked</option>
              </optgroup>
              <optgroup label="What the job gives you">
                <option value="highest-pay">Highest pay</option>
                <option value="most-part-time">Most part-time work available</option>
                <option value="most-women">Most women in the role</option>
                <option value="least-automation">Least exposed to automation</option>
              </optgroup>
              <optgroup label="Other">
                <option value="a-to-z">A to Z</option>
              </optgroup>
            </select>
          </div>
          <div class="filter-field">
            <label for="destination-compare">Compare which part of you</label>
            <select id="destination-compare" v-model="compareOption" data-testid="select-destination-compare">
              <option value="overall">overall load</option>
              <option value="Shoulders and upper arms">shoulders and upper arms</option>
              <option value="Lower back">lower back</option>
              <option value="Hands and wrists">hands and wrists</option>
              <option value="Knees">knees</option>
              <option value="Legs and feet">legs and feet</option>
              <option value="Whole body and fall risk">whole body and fall risk</option>
            </select>
          </div>
          <label class="checkbox-option">
            <input type="checkbox" :checked="showHarderMoves" data-testid="checkbox-harder-moves"
              @change="showHarderMoves = ($event.target as HTMLInputElement).checked" />
            <span>Show moves into equal or harder work</span>
          </label>
        </div>

        <div v-if="SHOW_LOCATION_FILTER" class="filter-field">
          <div class="filter-group-head">
            <label id="destination-states-label">State or territory</label>
            <span class="filter-group-actions">
              <button type="button" class="mini" @click="selectAllStates">All</button>
              <button type="button" class="mini" @click="clearStates">None</button>
            </span>
          </div>
          <div class="checkbox-grid" role="group" aria-labelledby="destination-states-label">
            <label v-for="state in AUSTRALIAN_STATES" :key="state.code" class="checkbox-option">
              <input type="checkbox" :checked="selectedStates.has(state.code)" @change="toggleState(state.code)" />
              <span>{{ state.name }}</span>
            </label>
          </div>
        </div>

        <div v-if="SHOW_LOCATION_FILTER" class="filter-field">
          <div class="filter-group-head">
            <label id="destination-sa4-label">Victorian region (SA4)</label>
            <span class="filter-group-actions">
              <button type="button" class="mini" @click="selectAllSa4Regions">All</button>
              <button type="button" class="mini" @click="clearSa4Regions">None</button>
            </span>
          </div>
          <p class="row-caption" style="margin-bottom: 8px">Choosing a region here will include Victoria automatically.
          </p>
          <div class="checkbox-grid tall" role="group" aria-labelledby="destination-sa4-label">
            <label v-for="sa4 in VIC_SA4_REGIONS" :key="sa4.code" class="checkbox-option">
              <input type="checkbox" :checked="selectedSa4Regions.has(sa4.code)" @change="toggleSa4Region(sa4.code)" />
              <span>{{ sa4.name }}</span>
            </label>
          </div>
        </div>

        <div class="filter-panel-foot">
          <button type="button" class="outline-button" data-testid="button-clear-filters" @click="clearAllFilters">Clear
            all filters</button>
          <button type="button" class="primary-button" data-testid="button-apply-filters"
            @click="isFiltersOpen = false">Show results</button>
        </div>
      </div>

      <p class="destination-filter-summary" data-testid="text-destination-count">
        {{ destinations.length }} move{{ destinations.length === 1 ? '' : 's' }}, {{ sortDescription
        }}{{ showHarderMoves ? '' : ' · harder moves hidden' }}
      </p>

      <div class="destination-workspace"
        :class="{ 'has-detail': selectedDestination, 'detail-expanded': isDetailExpanded }">
        <div class="destination-column" v-show="!isDetailExpanded">
          <div class="destination-list">
            <DestinationCard v-for="(destination, index) in destinations" :key="destination.id"
              :destination="destination" :index="index" :band="destination.bodyLoadBand"
              :active="index === selectedIndex" @open="openDestination(index)" />
          </div>
        </div>

        <article v-if="selectedDestination" class="destination-detail" :class="{ expanded: isDetailExpanded }"
          aria-live="polite">
          <div class="destination-detail-head">
            <div class="detail-head-actions">
              <button class="detail-icon-btn" type="button"
                :aria-label="isDetailExpanded ? 'Shrink destination detail' : 'Expand destination detail'"
                data-testid="button-toggle-expand-destination" @click="toggleDestinationExpanded">
                <svg v-if="!isDetailExpanded" viewBox="0 0 24 24" aria-hidden="true" width="16" height="16" fill="none"
                  stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M15 3h6v6" />
                  <path d="M9 21H3v-6" />
                  <path d="M21 3l-7 7" />
                  <path d="M3 21l7-7" />
                </svg>
                <svg v-else viewBox="0 0 24 24" aria-hidden="true" width="16" height="16" fill="none"
                  stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M4 14h6v6" />
                  <path d="M20 10h-6V4" />
                  <path d="M14 10l7-7" />
                  <path d="M3 21l7-7" />
                </svg>
              </button>
              <button class="detail-close" type="button" aria-label="Close destination detail"
                data-testid="button-close-destination" @click="closeDestination">
                <svg viewBox="0 0 24 24" aria-hidden="true" width="16" height="16" fill="none" stroke="currentColor"
                  stroke-width="2" stroke-linecap="round">
                  <path d="M6 6l12 12M18 6L6 18" />
                </svg>
              </button>
            </div>
            <p class="mlab" style="margin: 0 0 2px">If you moved here</p>
            <h3 data-testid="text-destination-title">{{ selectedDestination.title }}</h3>
          </div>
          <p v-if="selectedDestination.description" class="destination-why" data-testid="text-destination-description">
            {{ selectedDestination.description }}
          </p>
          <div class="destination-share">
            <SourceStatButton :source-id="selectedDestination.sourceId"
              :label="`${selectedDestination.share} percent transition share. Open source`"
              what="the share of people who made this move" data-testid="text-destination-share">
              <b>{{ selectedDestination.share.toFixed(1) }}%</b>
            </SourceStatButton>
            <span>of observed moves into this role</span>
          </div>

          <div class="detail-columns">
              <DetailSection title="What it costs your body" :expanded="isDetailExpanded" default-open>
                  <span v-if="detailLoadBand" class="load-pill" :class="detailLoadBand">
                    <svg v-if="detailLoadBand === 'down'" viewBox="0 0 16 16" aria-hidden="true" width="16" height="16"
                      fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M8 3v10M4 9l4 4 4-4" />
                    </svg>
                    <svg v-else-if="detailLoadBand === 'up'" viewBox="0 0 16 16" aria-hidden="true" width="16" height="16"
                      fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M8 13V3M4 7l4-4 4 4" />
                    </svg>
                    <svg v-else viewBox="0 0 16 16" aria-hidden="true" width="16" height="16" fill="none"
                      stroke="currentColor" stroke-width="1.6" stroke-linecap="round">
                      <path d="M3 8h10" />
                    </svg>
                    {{ detailLoadBandLabel[detailLoadBand] }}
                  </span>
                  <p class="trade-box">{{ detailTradeText }}</p>
                  <div v-if="detailFocusRegions.length" class="body-bars">
                    <div v-for="row in detailFocusRegions" :key="row.region" class="body-barrow">
                      <span class="body-bar-label">{{ row.region }}</span>
                      <span class="body-bar-track">
                        <span class="body-bar-fill now" :style="{ width: row.now + '%' }"></span>
                        <span class="body-bar-fill next" :style="{ width: row.next + '%' }"></span>
                      </span>
                      <span class="body-bar-diff">{{ row.diff > 0 ? '+' : '' }}{{ row.diff }}</span>
                    </div>
                    <p class="body-bar-legend"><i class="ln"></i> your job now &nbsp; <i class="lx"></i> this job</p>
                  </div>
              </DetailSection>

              <DetailSection title="Injury frequency signal, compared" :expanded="isDetailExpanded">
                  <p class="bandrow">
                    Your job now
                    <span v-if="tierBand(currentOccupationInjuryInsight?.insight?.tier)" class="band-badge"
                      :class="tierBand(currentOccupationInjuryInsight?.insight?.tier)">
                      {{ currentOccupationInjuryInsight?.insight?.tier }}
                    </span>
                    <span v-else class="row-caption">Not available for this occupation</span>
                  </p>
                  <p class="bandrow">
                    This job
                    <span v-if="tierBand(selectedDestination.tier)" class="band-badge" :class="tierBand(selectedDestination.tier)">
                      {{ selectedDestination.tier }}
                    </span>
                    <span v-else class="row-caption">Not available for this occupation</span>
                  </p>
                  <p class="bandrow-note">
                    From a research model trained on published physical demand and injury frequency data. It is not a
                    published statistic. It indicates only whether an occupation ranks higher or lower than typical. It
                    is not a predicted injury rate, not causal, and not a forecast.
                  </p>
              </DetailSection>

              <DetailSection title="Pay, hours and who works there" :expanded="isDetailExpanded">
                <p v-if="isDetailLoading" class="row-caption">Loading…</p>
              <template v-else>
                <div class="stat-featured">
                  <dt>Median weekly pay</dt>
                  <dd v-if="destinationProfile?.median_weekly_earnings != null">
                    ${{ Math.round(destinationProfile.median_weekly_earnings) }}
                  </dd>
                  <dd v-else class="unavailable">Not published for this occupation</dd>
                </div>

                <div class="stat-plain-grid">
                  <div class="dl">
                    <dt>Part-time</dt>
                    <dd v-if="destinationProfile?.part_time_share_pct != null">
                      {{ Math.round(destinationProfile.part_time_share_pct) }}<small>%</small>
                    </dd>
                    <dd v-else class="unavailable">Not published for this occupation</dd>
                  </div>
                  <div class="dl">
                    <dt>Women in role</dt>
                    <dd v-if="destWomenShareText">{{ destWomenShareText }}</dd>
                    <dd v-else class="unavailable">Not published for this occupation</dd>
                  </div>
                  <div class="dl">
                    <dt>Gender pay gap</dt>
                    <dd v-if="genderPayGapText">{{ genderPayGapText }}</dd>
                    <dd v-else class="unavailable">Not published for this occupation</dd>
                  </div>
                  <div class="dl">
                    <dt>Automation exposure</dt>
                    <dd v-if="destinationAiExposure?.automation_exposure != null">
                      {{ Math.round(destinationAiExposure.automation_exposure * 100) }}<small>/100</small>
                    </dd>
                    <dd v-else class="unavailable">Not published for this occupation</dd>
                  </div>
                </div>
              </template>
              </DetailSection>

              <DetailSection title="Compare with my job" :expanded="isDetailExpanded">
                <p v-if="isDetailLoading" class="row-caption">Loading…</p>
                <template v-else>
                  <div class="compare-head">
                  <b>{{ occupationTitle }}</b>
                  <span>vs</span>
                  <b>{{ selectedDestination.title }}</b>
                </div>

                <div class="compare-row">
                  <dt>Median weekly pay</dt>
                  <div class="compare-values">
                    <b class="compare-value">{{ currentPayText ?? 'Not published' }}</b>
                    <span class="compare-indicator">
                      <span v-if="medianPayComparison" class="compare-pill" :class="medianPayComparison.direction">
                        <template v-if="medianPayComparison.direction === 'better'">&uarr; Better</template>
                        <template v-else-if="medianPayComparison.direction === 'worse'">&darr; Worse</template>
                        <template v-else>&rarr; About the same</template>
                      </span>
                      <span v-if="!medianPayComparison || medianPayComparison.direction !== 'same'" class="compare-note">
                        {{ medianPayComparison ? medianPayComparison.note : 'Not published for one of these occupations' }}
                      </span>
                    </span>
                    <b class="compare-value">{{ destPayText ?? 'Not published' }}</b>
                  </div>
                </div>

                <div class="compare-row plain">
                  <dt>Gender pay gap</dt>
                  <div class="compare-values">
                    <b class="compare-value">{{ currentGenderPayGapText ?? 'Not published' }}</b>
                    <span class="compare-indicator">
                      <span v-if="payGapComparison" class="compare-pill" :class="payGapComparison.direction">
                        <template v-if="payGapComparison.direction === 'better'">&uarr; Better</template>
                        <template v-else-if="payGapComparison.direction === 'worse'">&darr; Worse</template>
                        <template v-else>&rarr; About the same</template>
                      </span>
                      <span v-if="!payGapComparison || payGapComparison.direction !== 'same'" class="compare-note">
                        {{ payGapComparison ? payGapComparison.note : 'Varies by specialisation' }}
                      </span>
                    </span>
                    <b class="compare-value">{{ genderPayGapText ?? 'Not published' }}</b>
                  </div>
                </div>

                <div class="compare-row">
                  <dt>Women in role</dt>
                  <div class="compare-values">
                    <b class="compare-value">{{ currentWomenShareText ?? 'Not published' }}</b>
                    <span class="compare-indicator">
                      <span v-if="womenInRoleComparison" class="compare-pill" :class="womenInRoleComparison.direction">
                        <template v-if="womenInRoleComparison.direction === 'better'">&uarr; Better</template>
                        <template v-else-if="womenInRoleComparison.direction === 'worse'">&darr; Worse</template>
                        <template v-else>&rarr; About the same</template>
                      </span>
                      <span v-if="!womenInRoleComparison || womenInRoleComparison.direction !== 'same'" class="compare-note">
                        {{ womenInRoleComparison ? womenInRoleComparison.note : 'Not published for one of these occupations' }}
                      </span>
                    </span>
                    <b class="compare-value">{{ destWomenShareText ?? 'Not published' }}</b>
                  </div>
                </div>

                <div class="compare-row plain">
                  <dt>Part-time available</dt>
                  <div class="compare-values">
                    <b class="compare-value">{{ currentPartTimeText ?? 'Not published' }}</b>
                    <span class="compare-indicator">
                      <span v-if="partTimeComparison" class="compare-pill" :class="partTimeComparison.direction">
                        <template v-if="partTimeComparison.direction === 'better'">&uarr; Better</template>
                        <template v-else-if="partTimeComparison.direction === 'worse'">&darr; Worse</template>
                        <template v-else>&rarr; About the same</template>
                      </span>
                      <span v-if="!partTimeComparison || partTimeComparison.direction !== 'same'" class="compare-note">
                        {{ partTimeComparison ? partTimeComparison.note : 'Not published for one of these occupations' }}
                      </span>
                    </span>
                    <b class="compare-value">{{ destPartTimeText ?? 'Not published' }}</b>
                  </div>
                </div>

                <div class="compare-row">
                  <dt>Automation exposure</dt>
                  <div class="compare-values">
                    <b class="compare-value">{{ currentAutomationText ?? 'Not published' }}</b>
                    <span class="compare-indicator">
                      <span v-if="automationComparison" class="compare-pill" :class="automationComparison.direction">
                        <template v-if="automationComparison.direction === 'better'">&uarr; Better</template>
                        <template v-else-if="automationComparison.direction === 'worse'">&darr; Worse</template>
                        <template v-else>&rarr; About the same</template>
                      </span>
                      <span v-if="!automationComparison || automationComparison.direction !== 'same'" class="compare-note">
                        {{ automationComparison ? automationComparison.note : 'Not published for one of these occupations' }}
                      </span>
                    </span>
                    <b class="compare-value">{{ destAutomationText ?? 'Not published' }}</b>
                  </div>
                </div>
                </template>
              </DetailSection>

              <DetailSection title="What the work involves" :expanded="isDetailExpanded">
                <p v-if="isDetailLoading" class="row-caption">Loading…</p>
                <ul v-else-if="selectedDestination.tasks?.length" class="task-list">
                  <li v-for="task in selectedDestination.tasks" :key="task">{{ task }}</li>
                </ul>
                <p v-else class="row-caption">Not published for this occupation.</p>
              </DetailSection>
          </div>
        </article>
      </div>

      <div v-if="selectedDestination" class="detail-source-row">
        <button class="srcbtn" type="button" data-testid="button-mobility-source-detail"
          @click="openMobilitySource">Where the share comes from</button>
        <button class="srcbtn" type="button" data-testid="button-body-scores-source"
          @click="openBodyScoresSource">Where the body scores come from</button>
      </div>

      <div class="action-row risk-actions">
        <button class="cta-g cta" type="button" data-testid="button-back-to-risk" @click="backToRisk">
          <svg viewBox="0 0 24 24" aria-hidden="true" width="16" height="16">
            <path d="m15 18-6-6 6-6" fill="none" stroke="currentColor" stroke-width="2" />
          </svg>
          Back to your risk
        </button>
        <button class="cta cta-g" type="button" data-testid="button-start-again" @click="startAgain">Start
          again</button>
      </div>
    </div>
  </section>
</template>
