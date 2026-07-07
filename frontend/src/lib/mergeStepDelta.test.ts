// Client half of the delta merge contract. The backend golden test
// (backend/tests/test_step_delta.py) proves merge == fresh fetch end to end;
// this suite pins the splice rule, reference identity, and fallback cases.
import { describe, expect, it } from 'vitest'
import { mergeStepDelta, spliceTail } from './mergeStepDelta'
import type { ApiBar, SessionBarsResponse, StepDelta, StepResponse } from './types'

const bar = (t: number, c: number, v = 100): ApiBar => ({
  t,
  o: c - 0.02,
  h: c + 0.05,
  l: c - 0.05,
  c,
  v,
  s: 'rth',
})

function prevResponse(): SessionBarsResponse {
  return {
    symbol: 'SPY',
    tf: '5m',
    day: '2026-06-17',
    clock: 1_000_300,
    done: false,
    sma200: 512.3,
    bars: [bar(1_000_000, 500.1), bar(1_000_300, 500.2)],
    days: [
      {
        day: '2026-06-17',
        half_day: false,
        session_open: 999_000,
        open: 1_000_000,
        close: 1_003_000,
        session_close: 1_004_000,
      },
    ],
    overlays: {
      vwap: [
        { t: 1_000_000, v: 500.05 },
        { t: 1_000_060, v: 500.07 },
      ],
      ema9: [
        { t: 1_000_000, v: 500.1 },
        { t: 1_000_300, v: 500.15 },
      ],
      ema20: [
        { t: 1_000_000, v: 500.08 },
        { t: 1_000_300, v: 500.12 },
      ],
    },
    rvol: 1.1,
  }
}

function stepResponse(delta: StepDelta | null, clock = 1_000_360): StepResponse {
  return { clock, cutoff: clock - 60, done: false, events: [], new_bars: {}, delta }
}

describe('spliceTail', () => {
  it('appends new elements after the cut', () => {
    const prev = [bar(1, 500), bar(2, 501)]
    expect(spliceTail(prev, [bar(3, 502)])).toEqual([bar(1, 500), bar(2, 501), bar(3, 502)])
  })

  it('replaces the trailing overlap (upsert of the partial bucket)', () => {
    const prev = [bar(1, 500), bar(2, 501)]
    const out = spliceTail(prev, [bar(2, 501.5, 220), bar(3, 502)])
    expect(out.map((b) => [b.t, b.c])).toEqual([
      [1, 500],
      [2, 501.5],
      [3, 502],
    ])
  })

  it('returns the SAME reference for an empty tail (downstream no-op)', () => {
    const prev = [bar(1, 500)]
    expect(spliceTail(prev, [])).toBe(prev)
  })

  it('keeps prefix element references (slice+concat, no cloning)', () => {
    const prev = [bar(1, 500), bar(2, 501)]
    const out = spliceTail(prev, [bar(2, 501.5)])
    expect(out[0]).toBe(prev[0])
  })
})

describe('mergeStepDelta', () => {
  it('splices bars and every overlay, and overwrites clock/done/rvol', () => {
    const prev = prevResponse()
    const merged = mergeStepDelta(
      prev,
      stepResponse({
        symbol: 'SPY',
        tf: '5m',
        bars: [bar(1_000_300, 500.25, 250), bar(1_000_600, 500.3)],
        overlays: {
          vwap: [{ t: 1_000_120, v: 500.09 }],
          ema9: [
            { t: 1_000_300, v: 500.18 },
            { t: 1_000_600, v: 500.2 },
          ],
          ema20: [
            { t: 1_000_300, v: 500.14 },
            { t: 1_000_600, v: 500.16 },
          ],
        },
        rvol: 1.25,
      }),
    )!
    expect(merged.bars.map((b) => [b.t, b.c])).toEqual([
      [1_000_000, 500.1],
      [1_000_300, 500.25],
      [1_000_600, 500.3],
    ])
    expect(merged.overlays.vwap.map((p) => p.t)).toEqual([1_000_000, 1_000_060, 1_000_120])
    expect(merged.overlays.ema9.at(-1)).toEqual({ t: 1_000_600, v: 500.2 })
    expect(merged.clock).toBe(1_000_360)
    expect(merged.rvol).toBe(1.25)
  })

  it('keeps series references on an all-empty delta but still updates clock/rvol', () => {
    const prev = prevResponse()
    const merged = mergeStepDelta(
      prev,
      stepResponse({
        symbol: 'SPY',
        tf: '5m',
        bars: [],
        overlays: { vwap: [], ema9: [], ema20: [] },
        rvol: 1.3,
      }),
    )!
    expect(merged.bars).toBe(prev.bars)
    expect(merged.overlays.vwap).toBe(prev.overlays.vwap)
    expect(merged.clock).toBe(1_000_360)
    expect(merged.rvol).toBe(1.3)
  })

  it('preserves days and sma200 untouched', () => {
    const prev = prevResponse()
    const merged = mergeStepDelta(
      prev,
      stepResponse({
        symbol: 'SPY',
        tf: '5m',
        bars: [bar(1_000_600, 500.3)],
        overlays: { vwap: [], ema9: [], ema20: [] },
        rvol: null,
      }),
    )!
    expect(merged.days).toBe(prev.days)
    expect(merged.sma200).toBe(512.3)
  })

  it('returns null without a delta or on tf/symbol mismatch', () => {
    const prev = prevResponse()
    const mk = (over: Partial<StepDelta>): StepDelta => ({
      symbol: 'SPY',
      tf: '5m',
      bars: [],
      overlays: { vwap: [], ema9: [], ema20: [] },
      rvol: null,
      ...over,
    })
    expect(mergeStepDelta(prev, stepResponse(null))).toBeNull()
    expect(mergeStepDelta(prev, stepResponse(mk({ tf: '15m' })))).toBeNull()
    expect(mergeStepDelta(prev, stepResponse(mk({ symbol: 'QQQ' })))).toBeNull()
  })
})
