import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { Timeframe } from '../lib/types'
import { ChartErrorBoundary } from '../chart/ChartErrorBoundary'
import { ChartPane } from '../chart/ChartPane'
import { TimeframeSwitcher } from '../chart/TimeframeSwitcher'
import { useBars } from '../chart/useBars'
import { WatchlistRail } from '../marketday/WatchlistRail'
import { ReplayControls } from '../replay/ReplayControls'
import { useReplaySession } from '../replay/useReplaySession'

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
  const [replayError, setReplayError] = useState<string | null>(null)

  const replay = useReplaySession()
  const inReplay = replay.session !== null

  const displayDay = symbolsQ.data?.display_day ?? null
  const browseQ = useBars(symbol, inReplay ? null : displayDay, tf)
  const sessionQ = useQuery({
    queryKey: ['sessionBars', replay.session?.id ?? 'none', tf],
    queryFn: () => api.sessionBars(replay.session!.id, tf),
    enabled: inReplay,
    staleTime: 0,
  })

  const data = inReplay ? sessionQ.data : browseQ.data
  const banner = closedBanner(symbolsQ.data?.state ?? 'unknown', displayDay)
  const queryError = inReplay ? sessionQ.error : browseQ.error

  const selectSymbol = (s: string) => {
    if (inReplay) replay.exit() // one symbol per replay session
    setSymbol(s)
  }

  const startReplay = async () => {
    if (!displayDay) return
    setReplayError(null)
    try {
      await replay.start(symbol, displayDay)
    } catch (e) {
      setReplayError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="market-layout">
      <WatchlistRail
        symbols={symbolsQ.data?.symbols ?? []}
        selected={symbol}
        onSelect={selectSymbol}
      />
      <section className="chart-area">
        <div className="chart-header">
          <span className="symbol">{symbol}</span>
          {inReplay ? (
            <ReplayControls
              clock={replay.clock}
              playing={replay.playing}
              speed={replay.speed}
              done={replay.done}
              onPlayPause={replay.playPause}
              onStepOne={replay.stepOne}
              onSpeed={replay.setSpeed}
              onRestart={() => void replay.restart()}
              onExit={replay.exit}
            />
          ) : (
            <>
              {banner && <span className="banner">{banner}</span>}
              {displayDay && (
                <button className="btn-replay" onClick={() => void startReplay()}>
                  ▶ Replay this day
                </button>
              )}
            </>
          )}
          {inReplay && sessionQ.data?.rvol != null && (
            <span className="rvol-chip">RVOL {sessionQ.data.rvol.toFixed(2)}</span>
          )}
          {(replayError || queryError) && (
            <span className="banner">⚠ {replayError ?? String(queryError)}</span>
          )}
          <TimeframeSwitcher tf={tf} onChange={setTf} />
        </div>
        <ChartErrorBoundary>
          <ChartPane
            bars={data?.bars ?? []}
            days={data?.days ?? []}
            overlays={data?.overlays}
            follow={inReplay && replay.playing}
            fitKey={`${symbol}:${displayDay}:${replay.session?.id ?? 'browse'}`}
          />
        </ChartErrorBoundary>
      </section>
    </div>
  )
}
