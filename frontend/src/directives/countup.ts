import type { Directive } from 'vue'

// Animates a number from 0 to data-c when the element enters the viewport, once.
// data-fmt (any value) switches to locale-formatted thousands separators.
export const vCountup: Directive<HTMLElement, void> = {
  mounted(el) {
    const to = Number(el.dataset.c)
    const fmt = el.dataset.fmt
    const show = (value: number) => {
      const rounded = Math.round(value)
      el.textContent = fmt ? rounded.toLocaleString('en-AU') : String(rounded)
    }
    const run = () => {
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || to === 0) {
        show(to)
        return
      }
      const start = performance.now()
      const duration = 1400
      const step = (now: number) => {
        const k = Math.min(1, (now - start) / duration)
        const eased = 1 - Math.pow(1 - k, 3)
        show(to * eased)
        if (k < 1) requestAnimationFrame(step)
      }
      requestAnimationFrame(step)
    }
    const rect = el.getBoundingClientRect()
    if (rect.top < window.innerHeight && rect.bottom > 0) {
      run()
      return
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            run()
            observer.unobserve(el)
          }
        }
      },
      { threshold: 0.4 },
    )
    observer.observe(el)
  },
}
