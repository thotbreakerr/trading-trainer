import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { Timeframe } from '../lib/types'
import { ChartErrorBoundary } from '../chart/ChartErrorBoundary'
import { ChartPane } from '../chart/ChartPane'
import { TimeframeSwitcher } from '../chart/TimeframeSwitcher'
import { useBars } from '../chart/useBars'
import { BriefingView } from '../marketday/BriefingView'
import { CalloutCard } from '../marketday/CalloutCard'
import { RecapView } from '../marketday/RecapView'
import { WatchlistRail } from '../marketday/WatchlistRail'
import { useCalloutSound } from '../marketday/useCalloutSound'
import { ReplayControls } from '../replay/ReplayControls'
import { useReplaySession } from '../replay/useReplaySession'
import { OrderTicket } from '../sim/OrderTicket'
import { PositionPanel } from '../sim/PositionPanel'

type View = 'briefing' | 'live' | 'recap'

const ct = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/Chicago',
  hour: 'numeric',
  minute: '2-digit',
})

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
  const queryClient = useQueryClient()
  const symbolsQ = useQuery({
    queryKey: ['symbols'],
    queryFn: api.symbols,
    refetchInterval: 60_000,
  })
  const mdQ = useQuery({
    queryKey: ['marketday'],
    queryFn: api.marketDayState,
    refetchInterval: 5_000,
  })
  const [symbol, setSymbol] = useState('SPY')
  const [tf, setTf] = useState<Timeframe>('5m')
  const [override, setOverride] = useState<View | null>(null)
  const [replayError, setReplayError] = useState<string | null>(null)

  const md = mdQ.data
  useCalloutSound(md?.callouts ?? [])

  const replay = useReplaySession()
  const inReplay = replay.session !== null

  const marketState = md?.market.state ?? symbolsQ.data?.state ?? 'unknown'
  const autoView: View =
    marketState === 'pre' ? 'briefing' : marketState === 'open' ? 'live' : 'recap'
  const view = override ?? autoView

  const displayDay = md?.session?.day ?? symbolsQ.data?.display_day ?? null
  const browseQ = useBars(symbol, inReplay ? null : displayDay, tf)
  const sessionQ = useQuery({
    queryKey: ['sessionBars', replay.session?.id ?? 'none', tf],
    queryFn: () => api.sessionBars(replay.session!.id, tf),
    enabled: inReplay,
    staleTime: 0,
  })
  const accountQ = useQuery({
    queryKey: ['account', replay.session?.id ?? 'none', replay.stepCount],
    queryFn: () => api.account(replay.session!.id),
    enabled: inReplay,
    staleTime: 0,
  })

  const data = inReplay ? sessionQ.data : browseQ.data
  const banner = closedBanner(marketState, displayDay)
  const lastBar = sessionQ.data?.bars[sessionQ.data.bars.length - 1]

  const selectSymbol = (s: string) => {
    if (inReplay) replay.exit()
    setSymbol(s)
  }

  const startReplay = async (sym = symbol, day = displayDay, startAt?: number) => {
    if (!day) return
    setReplayError(null)
    try {
      await replay.start(sym, day, startAt)
    } catch (e) {
      setReplayError(e instanceof Error ? e.message : String(e))
    }
  }

  const onReview = (sym: string, day: string, startAt: number) => {
    setOverride('live')
    setSymbol(sym)
    void startReplay(sym, day, startAt)
  }

  const act = async (id: string) => {
    await api.actOnCallout(id)
    await queryClient.invalidateQueries({ queryKey: ['marketday'] })
  }

  const viewChips = (
    <div className="view-chips">
      {(['briefing', 'live', 'recap'] as View[]).map((v) => (
        <button
          key={v}
          className={view === v ? 'active' : ''}
          onClick={() => setOverride(v === autoView ? null : v)}
        >
          {v}
        </button>
      ))}
    </div>
  )

  if (!inReplay && view === 'briefing') {
    return (
      <div className="md-takeover">
        {viewChips}
        <BriefingView />
      </div>
    )
  }
  if (!inReplay && view === 'recap') {
    return (
      <div className="md-takeover">
        {viewChips}
        <RecapView onReview={onReview} />
      </div>
    )
  }

  const showLiveRail = !inReplay && md?.session != null
  return (
    <div className={`market-layout ${inReplay || showLiveRail ? 'replaying' : ''}`}>
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
              {md?.session && (
                <span className="delay-chip" title="Free data is 15-minute delayed SIP">
                  {ct.format(new Date(md.session.clock * 1000))} CT · −15 min
                </span>
              )}
              {banner && <span className="banner">{banner}</span>}
              {md?.poll.stale && (
                <span className="stale-banner">
                  ⚠ data stale{md.poll.stale_since ? ` since ${ct.format(new Date(md.poll.stale_since))}` : ''} — retrying
                </span>
              )}
              {viewChips}
              {displayDay && (
                <button className="btn-replay" onClick={() => void startReplay()}>
                  ▶ Replay this day
                </button>
              )}
            </>
          )}
          {(replayError || (inReplay && sessionQ.error)) && (
            <span className="banner">⚠ {replayError ?? String(sessionQ.error)}</span>
          )}
          {inReplay && sessionQ.data?.rvol != null && (
            <span className="rvol-chip">RVOL {sessionQ.data.rvol.toFixed(2)}</span>
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
      {inReplay && replay.session && (
        <aside className="sim-rail">
          <OrderTicket
            sessionId={replay.session.id}
            lastPrice={lastBar?.c ?? null}
            equity={accountQ.data?.equity ?? null}
          />
          <PositionPanel
            sessionId={replay.session.id}
            stepCount={replay.stepCount}
            events={replay.events}
          />
        </aside>
      )}
      {showLiveRail && md && (
        <aside className="sim-rail">
          {md.account && (
            <div className="acct-row">
              <span>
                Equity <strong>${md.account.equity.toLocaleString()}</strong>
              </span>
              {md.account.flattened && <span className="muted">flat (EOD)</span>}
            </div>
          )}
          {md.account?.positions.map((p) => (
            <div key={p.symbol} className={`pos-row ${p.unrealized >= 0 ? 'up' : 'down'}`}>
              <strong>
                {p.qty > 0 ? 'LONG' : 'SHORT'} {Math.abs(p.qty)} {p.symbol}
              </strong>
              <span className="pnl">
                {p.unrealized >= 0 ? '+' : ''}
                {p.unrealized.toFixed(2)}
              </span>
            </div>
          ))}
          {!md.trading_unlocked && (
            <div className="muted">
              Observe mode — trading unlocks after Module 9 (doc rules).
            </div>
          )}
          <div className="callout-stack">
            {md.callouts.length === 0 && (
              <div className="muted">No setups fired yet — the coach is watching.</div>
            )}
            {md.callouts.map((c) => (
              <CalloutCard
                key={c.id}
                callout={c}
                tradingUnlocked={md.trading_unlocked}
                onAct={act}
              />
            ))}
          </div>
        </aside>
      )}
    </div>
  )
}
