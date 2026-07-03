// Session shading (pre / RTH / post) as a lightweight-charts v5 series
// primitive — compact port of the official SessionHighlighting plugin idea:
// one translucent vertical band per bar, colored by the bar's session tag.
import type { IChartApi, Time } from 'lightweight-charts'
import type { Session } from '../lib/types'

const SESSION_COLORS: Record<Session, string | null> = {
  pre: 'rgba(41, 98, 255, 0.08)',
  rth: null, // regular hours stay unshaded
  post: 'rgba(255, 152, 0, 0.07)',
}

interface BitmapScope {
  context: CanvasRenderingContext2D
  bitmapSize: { width: number; height: number }
  horizontalPixelRatio: number
}

export class SessionShading {
  private times: { t: number; s: Session }[] = []
  private chart: IChartApi | null = null
  private requestUpdate: (() => void) | null = null

  // ISeriesPrimitive hooks (structurally typed; attached via `as never` cast
  // at the callsite so minor interface renames between lib versions don't
  // break the build).
  attached(param: { chart: IChartApi; requestUpdate: () => void }) {
    this.chart = param.chart
    this.requestUpdate = param.requestUpdate
  }

  detached() {
    this.chart = null
    this.requestUpdate = null
  }

  setTimes(times: { t: number; s: Session }[]) {
    this.times = times
    this.requestUpdate?.()
  }

  paneViews() {
    return [
      {
        zOrder: () => 'bottom' as const,
        renderer: () => ({
          draw: (target: { useBitmapCoordinateSpace: (fn: (scope: BitmapScope) => void) => void }) =>
            target.useBitmapCoordinateSpace((scope) => this.draw(scope)),
        }),
      },
    ]
  }

  private draw(scope: BitmapScope) {
    const chart = this.chart
    if (!chart || this.times.length === 0) return
    const timeScale = chart.timeScale()
    const spacing = timeScale.options().barSpacing * scope.horizontalPixelRatio
    const ctx = scope.context
    for (const { t, s } of this.times) {
      const color = SESSION_COLORS[s]
      if (!color) continue
      const x = timeScale.timeToCoordinate(t as Time)
      if (x === null) continue
      const center = x * scope.horizontalPixelRatio
      ctx.fillStyle = color
      ctx.fillRect(center - spacing / 2, 0, spacing, scope.bitmapSize.height)
    }
  }
}
