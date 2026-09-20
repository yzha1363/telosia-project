import { reactive } from 'vue'

interface CookieState {
  isOpen: boolean
}

export const cookieState: CookieState = reactive({ isOpen: false })

export function showCookieModal() {
  cookieState.isOpen = true
}

export function hideCookieModal() {
  cookieState.isOpen = false
}

export function setCookiePreference(value: 'accepted' | 'declined') {
  try {
    localStorage.setItem('telosia-cookies', value)
  } catch {
    // localStorage unavailable — preference just won't persist across visits
  }
  cookieState.isOpen = false
}

export function maybeShowCookieModalOnFirstVisit() {
  try {
    if (!localStorage.getItem('telosia-cookies')) setTimeout(showCookieModal, 900)
  } catch {
    setTimeout(showCookieModal, 900)
  }
}
