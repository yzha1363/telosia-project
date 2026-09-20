import { reactive, watch } from 'vue'

export type DisplayMode = 'normal' | 'dark' | 'hc'
export type TextSize = 'normal' | 'large' | 'xlarge'

interface AccessibilityState {
  display: DisplayMode
  textSize: TextSize
  reduceMotion: boolean
  isPanelOpen: boolean
}

const root = document.documentElement

function initialDisplay(): DisplayMode {
  if (root.classList.contains('hc')) return 'hc'
  if (root.classList.contains('dark')) return 'dark'
  return 'normal'
}

export const a11yState: AccessibilityState = reactive({
  display: initialDisplay(),
  textSize: 'normal',
  reduceMotion: false,
  isPanelOpen: false,
})

watch(
  () => a11yState.display,
  (display) => {
    root.classList.remove('dark', 'hc')
    if (display === 'dark') root.classList.add('dark')
    else if (display === 'hc') root.classList.add('hc')
    root.setAttribute('data-theme', display === 'normal' ? 'light' : display)
    try {
      localStorage.setItem('telosia-theme', display === 'normal' ? 'light' : display)
    } catch {
      // localStorage unavailable — theme just won't persist across visits
    }
  },
  { immediate: true },
)

watch(
  () => a11yState.textSize,
  (size) => {
    root.classList.remove('fs-l', 'fs-xl')
    if (size === 'large') root.classList.add('fs-l')
    else if (size === 'xlarge') root.classList.add('fs-xl')
  },
  { immediate: true },
)

watch(
  () => a11yState.reduceMotion,
  (reduce) => {
    root.classList.toggle('no-mo', reduce)
    if (reduce) document.querySelectorAll('.reveal-up,.reveal-left,.reveal-right,.reveal-scale,.reveal-blur')
      .forEach((el) => el.classList.add('is-visible'))
  },
  { immediate: true },
)

export function resetAccessibility() {
  a11yState.display = 'normal'
  a11yState.textSize = 'normal'
  a11yState.reduceMotion = false
}
