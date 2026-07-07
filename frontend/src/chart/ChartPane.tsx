import { useEffect, useRef } from 'react'
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type ISeriesPrimitive,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import type { ApiBar, DayMeta, Point } from '../lib/types'
import { SessionShading } from './sessionShading'

export interface Overlays {
  vwap: Point[]
  ema9: Point[]
  ema20: Point[]
}

const OVERLAY_STYLE: Record<keyof Overlays, { color: string }> = {
  vwap: { color: '#f0b90b' },
  ema9: { color: '#29b6f6' },
  ema20: { color: '#ab47bc' },
}

// Display convention (doc §14): times shown in CT.
const ctTime = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/Chicago',
  hour: 'numeric',
  minute: '2-digit',
})
const ctDate = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/Chicago',
  month: 'short',
  day: 'numeric',
})
const ctFull = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/Chicago',
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
})

const UP = '#26a69a'
const DOWN = '#ef5350'

const toCandle = (b: ApiBar) => ({
  time: b.t as UTCTimestamp,
  open: b.o,
  high: b.h,
  low: b.l,
  close: b.c,
})
const toVolume = (b: ApiBar) => ({
  time: b.t as UTCTimestamp,
  value: b.v,
  color: b.c >= b.o ? 'rgba(38, 166, 154, 0.5)' : 'rgba(239, 83, 80, 0.5)',
})

/** Index from which `next` is a pure tail extension of the already-applied
 * `prev` (ref-equal prefix; the one shared trailing element may be replaced
 * in-place — same `t`, the merged partial bucket). null = not a tail (day/tf
 * switch, restart shrink, history rewrite) → caller must setData. */
function tailStart<T extends { t: number }>(prev: T[], next: T[]): number | null {
  if (next.length < prev.length) return null
  if (prev.length === 0) return 0
  const shared = prev.length - 1
  for (let i = 0; i < shared; i++) if (prev[i] !== next[i]) return null
  if (next[shared].t !== prev[shared].t) return null
  return next[shared] === prev[shared] ? prev.length : shared
}

export function ChartPane({
  bars,
  days,
  fitKey,
  overlays,
  follow = false,
}: {
  bars: ApiBar[]
  days: DayMeta[]
  /** When this changes (symbol/day switch), the view resets to the anchor
   * day; timeframe changes keep the current position (doc §15 checklist). */
  fitKey: string
  overlays?: Overlays
  /** Keep the latest bar in view as new bars arrive (replay while playing). */
  follow?: boolean
}) {
  const hostRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candlesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const overlayRefs = useRef<Record<keyof Overlays, ISeriesApi<'Line'> | null>>({
    vwap: null,
    ema9: null,
    ema20: null,
  })
  const shadingRef = useRef<SessionShading | null>(null)
  const lastFitKey = useRef<string>('')
  const appliedRef = useRef<{ fitKey: string; bars: ApiBar[]; overlays?: Overlays } | null>(null)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    const chart = createChart(host, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: '#131722' },
        textColor: '#787b86',
        panes: { separatorColor: '#2a2e39' },
      },
      grid: {
        vertLines: { color: 'rgba(42, 46, 57, 0.5)' },
        horzLines: { color: 'rgba(42, 46, 57, 0.5)' },
      },
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: '#2a2e39',
        tickMarkFormatter: (time: Time, tickMarkType: number) =>
          tickMarkType < 3
            ? ctDate.format(new Date((time as number) * 1000))
            : ctTime.format(new Date((time as number) * 1000)),
      },
      rightPriceScale: { borderColor: '#2a2e39' },
      localization: {
        timeFormatter: (time: Time) => `${ctFull.format(new Date((time as number) * 1000))} CT`,
      },
    })
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      wickUpColor: UP,
      wickDownColor: DOWN,
      borderVisible: false,
    })
    const volume = chart.addSeries(
      HistogramSeries,
      { priceFormat: { type: 'volume' }, priceScaleId: 'right' },
      1, // its own pane below the candles
    )
    for (const key of Object.keys(OVERLAY_STYLE) as (keyof Overlays)[]) {
      overlayRefs.current[key] = chart.addSeries(LineSeries, {
        color: OVERLAY_STYLE[key].color,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      })
    }
    const shading = new SessionShading()
    candles.attachPrimitive(shading as unknown as ISeriesPrimitive<Time>)
    // Volume pane gets ~1/5 of the height; stretch factors are relative so
    // this stays valid across resizes (unlike a pixel setHeight at mount,
    // which pins the pane before the chart has measured its container).
    try {
      chart.panes()[1]?.setStretchFactor(0.25)
    } catch {
      /* pane sizing is cosmetic — ignore if the API shifts */
    }
    chartRef.current = chart
    candlesRef.current = candles
    volumeRef.current = volume
    shadingRef.current = shading
    return () => {
      chart.remove()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    const chart = chartRef.current
    const candles = candlesRef.current
    const volume = volumeRef.current
    if (!chart || !candles || !volume) return

    // Incremental path: when the new arrays are tail extensions of what this
    // chart already shows (step-delta merges), apply series.update() per
    // changed bar/point instead of rebuilding every series. Any mismatch
    // (restart shrink, tf/day switch, history rewrite, update() throwing)
    // falls through to the setData path below.
    const prev = appliedRef.current
    if (prev && prev.fitKey === fitKey) {
      const barsFrom = tailStart(prev.bars, bars)
      const ovFrom = {
        vwap: tailStart(prev.overlays?.vwap ?? [], overlays?.vwap ?? []),
        ema9: tailStart(prev.overlays?.ema9 ?? [], overlays?.ema9 ?? []),
        ema20: tailStart(prev.overlays?.ema20 ?? [], overlays?.ema20 ?? []),
      }
      if (
        barsFrom !== null &&
        ovFrom.vwap !== null &&
        ovFrom.ema9 !== null &&
        ovFrom.ema20 !== null
      ) {
        try {
          const keepRange = chart.timeScale().getVisibleRange()
          for (let i = barsFrom; i < bars.length; i++) {
            candles.update(toCandle(bars[i]))
            volume.update(toVolume(bars[i]))
          }
          for (const key of Object.keys(OVERLAY_STYLE) as (keyof Overlays)[]) {
            const points = overlays?.[key] ?? []
            const series = overlayRefs.current[key]
            for (let i = ovFrom[key] as number; i < points.length; i++) {
              series?.update({ time: points[i].t as UTCTimestamp, value: points[i].v })
            }
          }
          if (barsFrom < bars.length) {
            shadingRef.current?.setTimes(bars.map((b) => ({ t: b.t, s: b.s })))
          }
          if (keepRange) chart.timeScale().setVisibleRange(keepRange)
          if (follow) chart.timeScale().scrollToRealTime()
          appliedRef.current = { fitKey, bars, overlays }
          return
        } catch {
          /* fall through to the full setData rebuild */
        }
      }
    }

    const keepRange = lastFitKey.current === fitKey ? chart.timeScale().getVisibleRange() : null

    candles.setData(bars.map(toCandle))
    volume.setData(bars.map(toVolume))
    shadingRef.current?.setTimes(bars.map((b) => ({ t: b.t, s: b.s })))
    for (const key of Object.keys(OVERLAY_STYLE) as (keyof Overlays)[]) {
      overlayRefs.current[key]?.setData(
        (overlays?.[key] ?? []).map((p) => ({ time: p.t as UTCTimestamp, value: p.v })),
      )
    }
    appliedRef.current = { fitKey, bars, overlays }

    if (keepRange) {
      chart.timeScale().setVisibleRange(keepRange) // tf switch: hold position
      if (follow) chart.timeScale().scrollToRealTime()
    } else if (bars.length > 0) {
      const anchor = days[days.length - 1]
      lastFitKey.current = fitKey
      if (anchor) {
        chart.timeScale().setVisibleRange({
          from: anchor.session_open as UTCTimestamp,
          to: anchor.session_close as UTCTimestamp,
        })
      } else {
        chart.timeScale().fitContent()
      }
    }
  }, [bars, days, fitKey, overlays, follow])

  return (
    <div className="chart-host">
      <div ref={hostRef} />
      {bars.length === 0 && <div className="chart-empty">No cached bars for this day yet.</div>}
    </div>
  )
}
