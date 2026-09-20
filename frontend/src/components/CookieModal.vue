<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { cookieState, hideCookieModal, setCookiePreference } from '../store/cookies'

const acceptBtn = ref<HTMLButtonElement | null>(null)

function choose(value: 'accepted' | 'declined') {
  setCookiePreference(value)
}

watch(
  () => cookieState.isOpen,
  (isOpen) => {
    if (isOpen) nextTick(() => acceptBtn.value?.focus())
  },
)

function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape' && cookieState.isOpen) hideCookieModal()
}
onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="ck-scrim" :class="{ open: cookieState.isOpen }" @click="hideCookieModal"></div>
  <aside
    class="ck-modal"
    :class="{ open: cookieState.isOpen }"
    :inert="!cookieState.isOpen || undefined"
    role="dialog"
    aria-modal="true"
    aria-labelledby="ckTitle"
    aria-describedby="ckBody"
    :aria-hidden="!cookieState.isOpen"
  >
    <div class="ck-card">
      <h3 id="ckTitle">Your privacy</h3>
      <div class="ck-body" id="ckBody">
        <p>
          Telosia uses strictly necessary cookies so the site works — things like remembering your text size and
          theme. We also offer optional analytics cookies so we can see which occupations people look at most, and
          add them sooner.
        </p>
        <p>Optional cookies only set if you accept them. You can change your mind any time from the Cookies link in the footer.</p>
      </div>
      <div class="ck-actions">
        <button class="cta cta-a" ref="acceptBtn" @click="choose('accepted')">Accept optional cookies</button>
        <button class="cta cta-g" @click="choose('declined')">Decline optional cookies</button>
      </div>
      <p class="ck-note">No personal information is stored. <button class="ck-link" @click="hideCookieModal">Close</button></p>
    </div>
  </aside>
</template>
