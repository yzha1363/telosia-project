<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { sourceDialogState, closeSource } from '../store/sourceDialog'

const closeBtn = ref<HTMLButtonElement | null>(null)
const isDefinitionOpen = ref(true)

const source = computed(() => sourceDialogState.source)
const coveragePeriod = computed(() => {
  const start = source.value?.coveragePeriodStart
  const end = source.value?.coveragePeriodEnd
  if (!start && !end) return null
  return `${start ?? '…'} – ${end ?? '…'}`
})
watch(
  () => sourceDialogState.isOpen,
  (isOpen) => {
    if (isOpen) {
      isDefinitionOpen.value = true
      nextTick(() => closeBtn.value?.focus())
    }
  },
)

function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape' && sourceDialogState.isOpen) closeSource()
}
onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="scrim" :class="{ open: sourceDialogState.isOpen }" @click="closeSource"></div>
  <aside
    class="drawer"
    :class="{ open: sourceDialogState.isOpen }"
    :inert="!sourceDialogState.isOpen || undefined"
    role="dialog"
    aria-modal="true"
    :aria-hidden="!sourceDialogState.isOpen"
    aria-labelledby="source-dialog-title"
  >
    <button class="drawer-close" ref="closeBtn" type="button" aria-label="Close" data-testid="button-close-source" @click="closeSource">
      &times;
    </button>
    <span class="lab">Where this comes from</span>
    <h3 id="source-dialog-title">{{ source?.publisher ?? 'Loading…' }}</h3>
    <p v-if="sourceDialogState.what" class="src-what">You opened this from {{ sourceDialogState.what }}.</p>

    <p v-if="sourceDialogState.isLoading" class="floor-rule">Loading…</p>
    <p v-else-if="sourceDialogState.error" class="floor-rule" data-testid="status-source-error">{{ sourceDialogState.error }}</p>
    <template v-else-if="source">
      <div class="dl"><dt>Published by</dt><dd>{{ source.publisher }}</dd></div>
      <div class="dl"><dt>Dataset</dt><dd>{{ source.datasetTitle }}</dd></div>
      <div class="dl" v-if="coveragePeriod"><dt>Covers</dt><dd>{{ coveragePeriod }}</dd></div>
      <div class="dl" v-if="source.updateFrequency"><dt>Updated</dt><dd>{{ source.updateFrequency }}</dd></div>
      <div class="dl" v-if="source.retrievalDate"><dt>We retrieved it</dt><dd>{{ source.retrievalDate }}</dd></div>
      <div class="dl" v-if="source.licence"><dt>Licence</dt><dd>{{ source.licence }}</dd></div>
      <a
        v-if="source.datasetUrl"
        class="tel-link"
        style="font-size: 0.8125rem; padding: 10px 18px; margin-top: 14px"
        :href="source.datasetUrl"
        target="_blank"
        rel="noreferrer"
      >
        Open the published source <span aria-hidden="true">&rarr;</span>
      </a>

      <div class="counts" v-if="source.plainLanguageNote">
        <h4>What this actually counts</h4>
        <p>{{ source.plainLanguageNote }}</p>
      </div>
    </template>
  </aside>
</template>
