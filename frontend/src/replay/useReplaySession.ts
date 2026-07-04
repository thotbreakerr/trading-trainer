import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { SessionInfo, SimEvent } from '../lib/types'

export type Speed = 1 | 2 | 5

/** Owns the replay step timer (doc §8): the CLIENT drives the clock — one
 * tick per second posting `speed` bars; pausing simply stops calling. */
export function useReplaySession() {
  const queryClient = useQueryClient()
  const [session, setSession] = useState<SessionInfo | null>(null)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState<Speed>(1)
  const [clock, setClock] = useState<number | null>(null)
  const [done, setDone] = useState(false)
  const [events, setEvents] = useState<SimEvent[]>([])
  const [stepCount, setStepCount] = useState(0)
  const inFlight = useRef(false)

  const invalidate = useCallback(
    (id: string) => queryClient.invalidateQueries({ queryKey: ['sessionBars', id] }),
    [queryClient],
  )

  const doStep = useCallback(
    async (bars: number) => {
      if (!session || inFlight.current) return
      inFlight.current = true
      try {
        const r = await api.stepSession(session.id, bars)
        setClock(r.clock)
        setDone(r.done)
        if (r.events.length) setEvents((prev) => [...prev, ...r.events].slice(-40))
        setStepCount((n) => n + 1)
        if (r.done) setPlaying(false)
        await invalidate(session.id)
      } finally {
        inFlight.current = false
      }
    },
    [session, invalidate],
  )

  useEffect(() => {
    if (!playing || !session) return
    const id = window.setInterval(() => void doStep(speed), 1000)
    return () => window.clearInterval(id)
  }, [playing, session, speed, doStep])

  const start = useCallback(async (symbol: string, day: string) => {
    const info = await api.createSession(symbol, day)
    setSession(info)
    setClock(info.clock)
    setDone(info.done)
    setPlaying(false)
    setEvents([])
    setStepCount(0)
  }, [])

  const restart = useCallback(async () => {
    if (!session) return
    const info = await api.restartSession(session.id)
    setClock(info.clock)
    setDone(false)
    setPlaying(false)
    setEvents([])
    setStepCount((n) => n + 1)
    await invalidate(session.id)
  }, [session, invalidate])

  const exit = useCallback(() => {
    if (session) void api.deleteSession(session.id)
    setSession(null)
    setPlaying(false)
    setClock(null)
    setDone(false)
    setEvents([])
  }, [session])

  return {
    session,
    playing,
    speed,
    clock,
    done,
    events,
    stepCount,
    start,
    exit,
    restart,
    stepOne: () => void doStep(1),
    playPause: () => setPlaying((p) => !p && !done),
    setSpeed,
  }
}
