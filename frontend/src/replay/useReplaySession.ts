import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { SessionInfo } from '../lib/types'

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
  }, [])

  const restart = useCallback(async () => {
    if (!session) return
    const info = await api.restartSession(session.id)
    setClock(info.clock)
    setDone(false)
    setPlaying(false)
    await invalidate(session.id)
  }, [session, invalidate])

  const exit = useCallback(() => {
    if (session) void api.deleteSession(session.id)
    setSession(null)
    setPlaying(false)
    setClock(null)
    setDone(false)
  }, [session])

  return {
    session,
    playing,
    speed,
    clock,
    done,
    start,
    exit,
    restart,
    stepOne: () => void doStep(1),
    playPause: () => setPlaying((p) => !p && !done),
    setSpeed,
  }
}
