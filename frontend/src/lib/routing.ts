import { useEffect, useState } from 'react'
import type React from 'react'

export type MarketPhase = 'plan' | 'trade' | 'review'
export type LearnSection = 'today' | 'curriculum' | 'drills' | 'scenarios'
export type PrimaryTab = 'market' | 'learn' | 'journal'

export type AppRoute =
  | { tab: 'market'; phase: MarketPhase; canonical: string }
  | { tab: 'learn'; section: LearnSection; moduleNumber: number | null; canonical: string }
  | { tab: 'journal'; tradeId: number | null; canonical: string }

const ROUTE_EVENT = 'trainer:navigate'

export function parseRoute(pathname: string): AppRoute {
  const clean = `/${pathname.split('?')[0].split('#')[0].replace(/^\/+|\/+$/g, '')}`
  const parts = clean.split('/').filter(Boolean)

  if (parts[0] === 'today' && ['plan', 'trade', 'review'].includes(parts[1])) {
    const phase = parts[1] as MarketPhase
    return { tab: 'market', phase, canonical: `/today/${phase}` }
  }

  if (parts[0] === 'learn') {
    if (parts[1] === 'module' && /^\d+$/.test(parts[2] ?? '')) {
      const moduleNumber = Number(parts[2])
      return {
        tab: 'learn',
        section: 'curriculum',
        moduleNumber,
        canonical: `/learn/module/${moduleNumber}`,
      }
    }
    if (['today', 'curriculum', 'drills', 'scenarios'].includes(parts[1])) {
      const section = parts[1] as LearnSection
      return { tab: 'learn', section, moduleNumber: null, canonical: `/learn/${section}` }
    }
    return { tab: 'learn', section: 'today', moduleNumber: null, canonical: '/learn/today' }
  }

  if (parts[0] === 'journal') {
    const tradeId = /^\d+$/.test(parts[1] ?? '') ? Number(parts[1]) : null
    return {
      tab: 'journal',
      tradeId,
      canonical: tradeId == null ? '/journal' : `/journal/${tradeId}`,
    }
  }

  return { tab: 'market', phase: 'trade', canonical: '/today/trade' }
}

export function navigate(to: string, options?: { replace?: boolean }) {
  const next = new URL(to, window.location.origin)
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`
  const target = `${next.pathname}${next.search}${next.hash}`
  if (target === current) return
  window.history[options?.replace ? 'replaceState' : 'pushState']({}, '', target)
  window.dispatchEvent(new Event(ROUTE_EVENT))
}

export function useAppLocation(): string {
  const read = () => `${window.location.pathname}${window.location.search}`
  const [location, setLocation] = useState(read)

  useEffect(() => {
    const update = () => setLocation(read())
    window.addEventListener('popstate', update)
    window.addEventListener(ROUTE_EVENT, update)
    return () => {
      window.removeEventListener('popstate', update)
      window.removeEventListener(ROUTE_EVENT, update)
    }
  }, [])

  return location
}

export function replaceRouteQuery(values: Record<string, string | null>) {
  const next = new URL(window.location.href)
  Object.entries(values).forEach(([key, value]) => {
    if (value == null || value === '') next.searchParams.delete(key)
    else next.searchParams.set(key, value)
  })
  navigate(`${next.pathname}${next.search}`, { replace: true })
}

export function handleAppLink(event: React.MouseEvent<HTMLAnchorElement>, href: string) {
  if (
    event.defaultPrevented ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  ) return
  event.preventDefault()
  navigate(href)
}
