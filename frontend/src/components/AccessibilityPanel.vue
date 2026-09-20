<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { a11yState, resetAccessibility, type DisplayMode, type TextSize } from '../store/accessibility'

function toggle() {
  a11yState.isPanelOpen = !a11yState.isPanelOpen
}

function setDisplay(display: DisplayMode) {
  a11yState.display = display
}

function setTextSize(size: TextSize) {
  a11yState.textSize = size
}

function toggleMotion() {
  a11yState.reduceMotion = !a11yState.reduceMotion
}

function onDocClick() {
  if (a11yState.isPanelOpen) a11yState.isPanelOpen = false
}

function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape' && a11yState.isPanelOpen) a11yState.isPanelOpen = false
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
  window.addEventListener('keydown', onKey)
})
onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
  window.removeEventListener('keydown', onKey)
})
</script>

<template>
  <button
    class="a11y-toggle"
    type="button"
    :aria-expanded="a11yState.isPanelOpen"
    aria-controls="a11yPanel"
    aria-label="Display and accessibility options"
    data-testid="button-accessibility"
    @click.stop="toggle"
  >
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="4" r="2" />
      <path
        d="M20.5 7.5c-2.5.9-5.4 1.4-8.5 1.4s-6-.5-8.5-1.4a1 1 0 1 0-.7 1.9c1.9.7 4 1.2 6.2 1.4v2.6L6.3 20a1 1 0 0 0 1.8.9L12 14.6l3.9 6.3a1 1 0 0 0 1.8-.9L14 13.4v-2.6c2.2-.2 4.3-.7 6.2-1.4a1 1 0 1 0-.7-1.9z"
      />
    </svg>
  </button>

  <div
    id="a11yPanel"
    class="a11y-panel"
    :class="{ open: a11yState.isPanelOpen }"
    role="dialog"
    aria-label="Display and accessibility options"
    :aria-hidden="!a11yState.isPanelOpen"
    :inert="!a11yState.isPanelOpen || undefined"
    @click.stop
  >
    <h4>Display options</h4>
    <p class="sub">How the app looks and moves for you. Saved only in this browser.</p>

    <div class="a11y-row">
      <span class="a11y-label">Appearance</span>
      <div class="segs" role="group" aria-label="Colour theme">
        <button :aria-pressed="a11yState.display === 'normal'" @click="setDisplay('normal')">Light</button>
        <button :aria-pressed="a11yState.display === 'dark'" @click="setDisplay('dark')">Dark</button>
        <button :aria-pressed="a11yState.display === 'hc'" @click="setDisplay('hc')">High contrast</button>
      </div>
    </div>

    <div class="a11y-row">
      <span class="a11y-label">Text size</span>
      <div class="segs" role="group" aria-label="Text size">
        <button class="s1" :aria-pressed="a11yState.textSize === 'normal'" @click="setTextSize('normal')">Normal</button>
        <button class="s2" :aria-pressed="a11yState.textSize === 'large'" @click="setTextSize('large')">Larger</button>
        <button class="s3" :aria-pressed="a11yState.textSize === 'xlarge'" @click="setTextSize('xlarge')">Largest</button>
      </div>
    </div>

    <div class="swrow">
      <span>Reduce motion<small>Turns off movement and animation</small></span>
      <button
        class="sw-t"
        :aria-pressed="a11yState.reduceMotion"
        aria-label="Reduce motion"
        data-testid="button-reduce-motion"
        @click="toggleMotion"
      ></button>
    </div>
    <button class="a11y-reset" @click="resetAccessibility">Reset to default</button>
  </div>
</template>
