import { useCallback, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { DrillResolution, Timeframe } from '../lib/types'
import { useReplaySession } from '../replay/useReplaySession'

export type DrillPhase = 'live' | 'resolved' | 'summary'

/** The drill loop: a run of N blind instances → act or pass → reveal → next.
 * Composes useReplaySession; attempt sessions are created server-side (the
 * hook adopts them), and the tally accumulates tiers / passes per run. */
export function useDrillRun(setup: string, count: number, tf: Timeframe) {
  const queryClient = useQueryClient()
  const replay = useReplaySession(tf)
  const [runId, setRunId] = useState<string | null>(null)
  const [total, setTotal] = useState(0)
  const [idx, setIdx] = useState(0)
  const [attemptId, setAttemptId] = useState<string | null>(null)
  const [phase, setPhase] = useState<DrillPhase>('live')
  const [resolution, setResolution] = useState<DrillResolution | null>(null)
  const [tally, setTally] = useState<Record<string, number>>({})
  const [error, setError] = useState<string | null>(null)
  const [empty, setEmpty] = useState(false)
  const [busy, setBusy] = useState(false)

  const advance = useCallback(
    async (rid: string) => {
      const r = await api.drillNext(rid)
      if (r.done) {
        setPhase('summary')
        replay.exit()
        return
      }
      setAttemptId(r.attempt_id)
      setIdx(r.idx)
      setTotal(r.total)
      setResolution(null)
      setPhase('live')
      replay.adopt(r.session)
    },
    [replay],
  )

  const startRun = useCallback(async () => {
    setError(null)
    setEmpty(false)
    setBusy(true)
    try {
      const run = await api.drillStartRun(setup, count)
      if (!run.run_id || run.total === 0) {
        setEmpty(true)
        return
      }
      setRunId(run.run_id)
      setTotal(run.total)
      setTally({})
      await advance(run.run_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [setup, count, advance])

  /** Pass and reveal are the same server call — `took` is server-derived. */
  const resolve = useCallback(async () => {
    if (!attemptId) return
    setBusy(true)
    try {
      const r = await api.drillResolve(attemptId)
      setResolution(r)
      setPhase('resolved')
      const key = r.user.took ? (r.user.grade?.tier ?? 'ungraded') : 'passed'
      setTally((t) => ({ ...t, [key]: (t[key] ?? 0) + 1 }))
      await queryClient.invalidateQueries({ queryKey: ['journalTrades'] })
      await queryClient.invalidateQueries({ queryKey: ['drillSetups'] })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [attemptId, queryClient])

  const nextInstance = useCallback(async () => {
    if (!runId) return
    setError(null)
    setBusy(true)
    try {
      await advance(runId)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [runId, advance])

  return {
    replay,
    phase,
    idx,
    total,
    tally,
    resolution,
    error,
    empty,
    busy,
    startRun,
    resolve,
    nextInstance,
  }
}
