import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { LessonStepData, SessionInfo } from '../lib/types'

/** Replay driver for lesson Watch/Practice steps. Watch steps auto-advance
 * to each scripted pause (doc §8 "lesson auto-jump"); Practice steps get the
 * free play/pause/speed controls. */
export function useLessonReplay(moduleNumber: number, step: LessonStepData | null) {
  const queryClient = useQueryClient()
  const [session, setSession] = useState<SessionInfo | null>(null)
  const [clock, setClock] = useState<number | null>(null)
  const [done, setDone] = useState(false)
  const [pauseIndex, setPauseIndex] = useState(0)
  const [atPause, setAtPause] = useState(false)
  const [running, setRunning] = useState(false) // auto-advance toward target
  const [playing, setPlaying] = useState(false) // free play (practice)
  const [speed, setSpeed] = useState<1 | 2 | 5>(2)
  const busy = useRef(false)
  const stepKey = step ? `${moduleNumber}:${step.index}` : null

  const hasReplay = step != null && (step.type === 'replay' || step.type === 'practice')
  const pauses = step?.pauses ?? []

  useEffect(() => {
    setSession(null)
    setClock(null)
    setDone(false)
    setPauseIndex(0)
    setAtPause(false)
    setRunning(false)
    setPlaying(false)
    if (!hasReplay || step == null) return
    let cancelled = false
    api
      .lessonSession(moduleNumber, step.index)
      .then((info) => {
        if (cancelled) return
        setSession(info)
        setClock(info.clock)
        setDone(info.done)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stepKey])

  const invalidate = useCallback(
    (id: string) => queryClient.invalidateQueries({ queryKey: ['sessionBars', id] }),
    [queryClient],
  )

  const stepBars = useCallback(
    async (bars: number) => {
      if (!session || busy.current) return null
      busy.current = true
      try {
        const r = await api.stepSession(session.id, bars)
        setClock(r.clock)
        setDone(r.done)
        await invalidate(session.id)
        return r
      } finally {
        busy.current = false
      }
    },
    [session, invalidate],
  )

  // Auto-advance toward the next pause (or session end) while `running`.
  useEffect(() => {
    if (!running || !session || clock == null) return
    const target = pauses[pauseIndex]?.ts ?? session.end_at
    if (clock >= target || done) {
      setRunning(false)
      if (pauses[pauseIndex] && clock >= pauses[pauseIndex].ts) setAtPause(true)
      return
    }
    const remaining = Math.ceil((target - clock) / 60)
    const timer = window.setTimeout(() => void stepBars(Math.min(30, remaining)), 220)
    return () => window.clearTimeout(timer)
  }, [running, clock, done, session, pauses, pauseIndex, stepBars])

  // Free play (practice): 1 tick/second at `speed` bars.
  useEffect(() => {
    if (!playing || !session) return
    const id = window.setInterval(() => void stepBars(speed), 1000)
    return () => window.clearInterval(id)
  }, [playing, session, speed, stepBars])

  useEffect(() => {
    if (done) setPlaying(false)
  }, [done])

  const playToNextPause = () => {
    setAtPause(false)
    setRunning(true)
  }

  const continueFromPause = () => {
    setAtPause(false)
    setPauseIndex((i) => i + 1)
  }

  const restart = async () => {
    if (!session) return
    const info = await api.restartSession(session.id)
    setClock(info.clock)
    setDone(false)
    setPauseIndex(0)
    setAtPause(false)
    setRunning(false)
    setPlaying(false)
    await invalidate(session.id)
  }

  const scriptFinished =
    hasReplay && step?.type === 'replay' ? pauseIndex >= pauses.length && !atPause : true

  return {
    session,
    clock,
    done,
    running,
    playing,
    speed,
    atPause,
    pauseIndex,
    pauses,
    scriptFinished,
    playToNextPause,
    continueFromPause,
    stepOne: () => void stepBars(1),
    playPause: () => setPlaying((p) => !p),
    setSpeed,
    restart: () => void restart(),
  }
}
