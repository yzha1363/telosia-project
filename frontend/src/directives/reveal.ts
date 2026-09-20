import type { Directive } from 'vue'

// Toggles an `is-visible` class every time an element crosses into or out of the viewport,
// so CSS can animate it in and out (see the `.reveal-*` variants in styles.css) — replays on
// every scroll pass, not just the first. Skips the observer entirely when the user has
// requested reduced motion, showing content immediately instead of animating it.
export const vReveal: Directive<HTMLElement, void> = {
  mounted(el) {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      el.classList.add('is-visible')
      return
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          el.classList.toggle('is-visible', entry.isIntersecting)
        }
      },
      { threshold: 0.15, rootMargin: '0px 0px -40px 0px' },
    )
    observer.observe(el)
  },
}
