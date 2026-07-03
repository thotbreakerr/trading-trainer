import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { Timeframe } from '../lib/types'
import { ChartPane } from '../chart/ChartPane'
import { TimeframeSwitcher } from '../chart/TimeframeSwitcher'
import { useBars } from '../chart/useBars'
import { WatchlistRail } from '../marketday/WatchlistRail'

function closedBanner(state: string, displayDay: string | null): string | null {
  if (state !== 'closed' || !displayDay) return null
  const d = new Date(`${displayDay}T12:00:00Z`)
  const label = new Intl.DateTimeFormat('en-US', {
    weekday: 'long',
    month: 'short',
    day: 'numeric',
  }).format(d)
  return `Market closed — showing ${label}`
}

export function MarketDayTab() {
  const symbolsQ = useQuery({
    queryKey: ['symbols'],
    queryFn: api.symbols,
    refetchInterval: 60_000,
  })
  const [symbol, setSymbol] = useState('SPY')
  const [tf, setTf] = useState<Timeframe>('5m')

  const displayDay = symbolsQ.data?.display_day ?? null
  const barsQ = useBars(symbol, displayDay, tf)
  const banner = closedBanner(symbolsQ.data?.state ?? 'unknown', displayDay)

  return (
    <div className="market-layout">
      <WatchlistRail
        symbols={symbolsQ.data?.symbols ?? []}
        selected={symbol}
        onSelect={setSymbol}
      />
      <section className="chart-area">
        <div className="chart-header">
          <span className="symbol">{symbol}</span>
          {banner && <span className="banner">{banner}</span>}
          {barsQ.isError && <span className="banner">⚠ {String(barsQ.error)}</span>}
          <TimeframeSwitcher tf={tf} onChange={setTf} />
        </div>
        <ChartPane
          bars={barsQ.data?.bars ?? []}
          days={barsQ.data?.days ?? []}
          fitKey={`${symbol}:${displayDay}`}
        />
      </section>
    </div>
  )
}
