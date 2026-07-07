// Client half of the step-delta merge contract (backend/app/api/chart_payload.py):
// per series, drop every cached element with t >= tail[0].t, then append the
// tail; an empty tail keeps the cached series (same reference — downstream
// consumers can no-op); clock/done/rvol always overwrite. The backend golden
// test (tests/test_step_delta.py) proves merge(prev, delta) == fresh fetch.
import type { QueryClient } from '@tanstack/react-query'
import type { SessionBarsResponse, StepResponse } from './types'

export function spliceTail<T extends { t: number }>(prev: T[], tail: T[]): T[] {
  if (tail.length === 0) return prev
  const from = tail[0].t
  let i = prev.length
  while (i > 0 && prev[i - 1].t >= from) i--
  return prev.slice(0, i).concat(tail)
}

/** Pure merge; null means "cannot merge" (missing delta / tf or symbol
 * mismatch) and the caller should fall back to a full refetch. */
export function mergeStepDelta(
  prev: SessionBarsResponse,
  step: StepResponse,
): SessionBarsResponse | null {
  const d = step.delta
  if (!d || d.tf !== prev.tf || d.symbol !== prev.symbol) return null
  return {
    ...prev,
    clock: step.clock,
    done: step.done,
    rvol: d.rvol,
    bars: spliceTail(prev.bars, d.bars),
    overlays: {
      vwap: spliceTail(prev.overlays.vwap, d.overlays.vwap),
      ema9: spliceTail(prev.overlays.ema9, d.overlays.ema9),
      ema20: spliceTail(prev.overlays.ema20, d.overlays.ema20),
    },
  }
}

/** Apply a step response to the sessionBars cache: merge in place when
 * possible, otherwise invalidate (exactly the pre-delta behavior). Keyed by
 * the RESPONSE tf, not the current UI tf — a mid-flight timeframe switch
 * merges into the old entry while the new tf mounts and full-fetches. */
export async function applyStepDelta(
  queryClient: QueryClient,
  sessionId: string,
  step: StepResponse,
): Promise<void> {
  const d = step.delta
  if (d) {
    const key = ['sessionBars', sessionId, d.tf]
    const prev = queryClient.getQueryData<SessionBarsResponse>(key)
    if (prev) {
      const merged = mergeStepDelta(prev, step)
      if (merged) {
        queryClient.setQueryData(key, merged)
        return
      }
    }
  }
  await queryClient.invalidateQueries({ queryKey: ['sessionBars', sessionId] })
}
