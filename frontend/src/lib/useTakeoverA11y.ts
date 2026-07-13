import { useCallback, useEffect, useRef, useState } from 'react'

const FOCUSABLE = 'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

export function useTakeoverA11y(onExit: () => void, active = true) {
  const [container, setContainer] = useState<HTMLDivElement | null>(null)
  const containerRef = useCallback((node: HTMLDivElement | null) => setContainer(node), [])
  const exitRef = useRef(onExit)
  exitRef.current = onExit

  useEffect(() => {
    if (!active) return
    if (!container) return
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const app = container.closest('.app')
    const hiddenSiblings = app
      ? Array.from(app.children).filter((child) => !child.contains(container)) as HTMLElement[]
      : []
    const previousHidden = hiddenSiblings.map((element) => ({
      element,
      ariaHidden: element.getAttribute('aria-hidden'),
      inert: element.inert,
    }))
    hiddenSiblings.forEach((element) => {
      element.inert = true
      element.setAttribute('aria-hidden', 'true')
    })

    const frame = window.requestAnimationFrame(() => {
      const first = container.querySelector<HTMLElement>(FOCUSABLE)
      ;(first ?? container).focus()
    })

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        exitRef.current()
        return
      }
      if (event.key !== 'Tab') return
      const focusable = Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE))
      if (focusable.length === 0) {
        event.preventDefault()
        container.focus()
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)

    return () => {
      window.cancelAnimationFrame(frame)
      document.removeEventListener('keydown', onKeyDown)
      previousHidden.forEach(({ element, ariaHidden, inert }) => {
        element.inert = inert
        if (ariaHidden == null) element.removeAttribute('aria-hidden')
        else element.setAttribute('aria-hidden', ariaHidden)
      })
      previousFocus?.focus()
    }
  }, [active, container])

  return containerRef
}
