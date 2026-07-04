import { useEffect, useState } from 'react'

/** The only interaction mode inside lessons (doc §7): everything dims except
 * one target element; an arrowed label points at it; ONLY the target is
 * clickable — the dim panes swallow every other click by construction. */
export function GuidedPointer({
  target,
  label,
  onTargetClick,
}: {
  target: string
  label: string
  onTargetClick: () => void
}) {
  const [rect, setRect] = useState<DOMRect | null>(null)

  useEffect(() => {
    const find = () => {
      const el = document.querySelector(`[data-pointer-id="${target}"]`)
      setRect(el ? el.getBoundingClientRect() : null)
    }
    find()
    const interval = window.setInterval(find, 300)
    window.addEventListener('resize', find)
    return () => {
      window.clearInterval(interval)
      window.removeEventListener('resize', find)
    }
  }, [target])

  useEffect(() => {
    const el = document.querySelector(`[data-pointer-id="${target}"]`)
    if (!el) return
    const handler = () => onTargetClick()
    el.addEventListener('click', handler)
    return () => el.removeEventListener('click', handler)
  }, [target, onTargetClick, rect])

  if (!rect) return null
  const pad = 6
  const top = Math.max(rect.top - pad, 0)
  const left = Math.max(rect.left - pad, 0)
  const right = rect.right + pad
  const bottom = rect.bottom + pad
  const labelBelow = rect.bottom < window.innerHeight * 0.7

  return (
    <>
      <div className="gp-dim" style={{ top: 0, left: 0, right: 0, height: top }} />
      <div className="gp-dim" style={{ top, left: 0, width: left, height: bottom - top }} />
      <div className="gp-dim" style={{ top, left: right, right: 0, height: bottom - top }} />
      <div className="gp-dim" style={{ top: bottom, left: 0, right: 0, bottom: 0 }} />
      <div
        className="gp-ring"
        style={{ top, left, width: right - left, height: bottom - top }}
      />
      <div
        className="gp-label"
        style={
          labelBelow
            ? { top: bottom + 14, left: Math.max(8, (left + right) / 2 - 140) }
            : { top: top - 60, left: Math.max(8, (left + right) / 2 - 140) }
        }
      >
        <span className="gp-arrow">{labelBelow ? '▲' : '▼'}</span> {label}
      </div>
    </>
  )
}
