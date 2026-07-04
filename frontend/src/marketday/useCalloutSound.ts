import { useEffect, useRef } from 'react'
import type { CalloutData } from '../lib/types'

/** In-app sound for new unlocked callouts (doc §11) — a short WebAudio chirp,
 * primed by the first user gesture (browser autoplay policy). */
export function useCalloutSound(callouts: CalloutData[]) {
  const ctxRef = useRef<AudioContext | null>(null)
  const seen = useRef<Set<string>>(new Set())
  const primed = useRef(false)

  useEffect(() => {
    const prime = () => {
      if (!primed.current) {
        ctxRef.current = new AudioContext()
        primed.current = true
      }
    }
    window.addEventListener('pointerdown', prime, { once: true })
    return () => window.removeEventListener('pointerdown', prime)
  }, [])

  useEffect(() => {
    const fresh = callouts.filter(
      (c) => !c.locked && c.status === 'watching' && !seen.current.has(c.id),
    )
    for (const c of callouts) seen.current.add(c.id)
    if (!fresh.length || !ctxRef.current) return
    const ctx = ctxRef.current
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.frequency.value = 880
    gain.gain.setValueAtTime(0.12, ctx.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4)
    osc.connect(gain).connect(ctx.destination)
    osc.start()
    osc.stop(ctx.currentTime + 0.4)
  }, [callouts])
}
