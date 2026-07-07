// Pure drawing math for the session-shading primitive: band geometry in
// bitmap coordinates, per-session colors, skip rules.
import { describe, expect, it, vi } from 'vitest'
import { SessionShading } from './sessionShading'
import type { Session } from '../lib/types'

const HEIGHT = 400

function makeFakes(coords: Record<number, number | null>, barSpacing = 10) {
  const rects: { x: number; y: number; w: number; h: number; fill: string }[] = []
  let fillStyle = ''
  const ctx = {
    set fillStyle(v: string) {
      fillStyle = v
    },
    fillRect(x: number, y: number, w: number, h: number) {
      rects.push({ x, y, w, h, fill: fillStyle })
    },
  }
  const chart = {
    timeScale: () => ({
      options: () => ({ barSpacing }),
      timeToCoordinate: (t: number) => coords[t] ?? null,
    }),
  }
  const scope = {
    context: ctx as unknown as CanvasRenderingContext2D,
    bitmapSize: { width: 800, height: HEIGHT },
    horizontalPixelRatio: 2,
  }
  return { chart, scope, rects }
}

function draw(shading: SessionShading, scope: unknown) {
  const view = shading.paneViews()[0]
  view.renderer().draw({
    useBitmapCoordinateSpace: (fn: (s: never) => void) => fn(scope as never),
  })
}

function attach(shading: SessionShading, chart: unknown, requestUpdate = () => {}) {
  shading.attached({ chart: chart as never, requestUpdate })
}

describe('SessionShading', () => {
  it('draws nothing for RTH bars', () => {
    const { chart, scope, rects } = makeFakes({ 100: 50 })
    const shading = new SessionShading()
    attach(shading, chart)
    shading.setTimes([{ t: 100, s: 'rth' as Session }])
    draw(shading, scope)
    expect(rects).toEqual([])
  })

  it('draws pre/post bands with the exact palette colors', () => {
    const { chart, scope, rects } = makeFakes({ 100: 50, 200: 60 })
    const shading = new SessionShading()
    attach(shading, chart)
    shading.setTimes([
      { t: 100, s: 'pre' as Session },
      { t: 200, s: 'post' as Session },
    ])
    draw(shading, scope)
    expect(rects.map((r) => r.fill)).toEqual([
      'rgba(41, 98, 255, 0.08)',
      'rgba(255, 152, 0, 0.07)',
    ])
  })

  it('scales band geometry by the pixel ratio', () => {
    // x=50, ratio=2 -> center 100; barSpacing 10 * ratio -> width 20
    const { chart, scope, rects } = makeFakes({ 100: 50 })
    const shading = new SessionShading()
    attach(shading, chart)
    shading.setTimes([{ t: 100, s: 'pre' as Session }])
    draw(shading, scope)
    expect(rects).toEqual([{ x: 90, y: 0, w: 20, h: HEIGHT, fill: 'rgba(41, 98, 255, 0.08)' }])
  })

  it('skips bars that are off-screen (null coordinate)', () => {
    const { chart, scope, rects } = makeFakes({ 100: null })
    const shading = new SessionShading()
    attach(shading, chart)
    shading.setTimes([{ t: 100, s: 'pre' as Session }])
    draw(shading, scope)
    expect(rects).toEqual([])
  })

  it('draws nothing before attach and after detach', () => {
    const { chart, scope, rects } = makeFakes({ 100: 50 })
    const shading = new SessionShading()
    shading.setTimes([{ t: 100, s: 'pre' as Session }])
    draw(shading, scope) // never attached
    expect(rects).toEqual([])
    attach(shading, chart)
    shading.detached()
    draw(shading, scope)
    expect(rects).toEqual([])
  })

  it('setTimes requests a repaint and zOrder is bottom', () => {
    const { chart } = makeFakes({})
    const shading = new SessionShading()
    const requestUpdate = vi.fn()
    attach(shading, chart, requestUpdate)
    shading.setTimes([])
    expect(requestUpdate).toHaveBeenCalledOnce()
    expect(shading.paneViews()[0].zOrder()).toBe('bottom')
  })
})
