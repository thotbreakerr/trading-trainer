import { useEffect, useState, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { replaceRouteQuery, type MarketPhase } from '../lib/routing'
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

const PHASES: { id: MarketPhase; label: string; hint: string }[] = [
  { id: 'plan', label: 'Plan', hint: 'Prepare levels and commitments' },
  { id: 'trade', label: 'Trade', hint: 'Watch, practice, and manage risk' },
  { id: 'review', label: 'Review', hint: 'Study decisions and outcomes' },
]

const ct = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/Chicago',
  hour: 'numeric',
  minute: '2-digit',
})

function initialSymbol(): string {
  const value = new URLSearchParams(window.location.search).get('symbol')?.toUpperCase()
  return value && /^[A-Z.]{1,8}$/.test(value) ? value : 'SPY'
}

function initialTimeframe(): Timeframe {
  const value = new URLSearchParams(window.location.search).get('tf')
  return value === '1m' || value === '5m' || value === '15m' || value === '1h' ? value : '5m'
}

function currentStage(state: string): number {
  if (state === 'pre') return 0
  if (state === 'open') return 1
  if (state === 'post' || state === 'closed') return 2
  return 1
}

function stateLabel(state: string): string {
  if (state === 'pre') return 'Pre-market planning window'
  if (state === 'open') return 'Market session in progress'
  if (state === 'post') return 'After-hours review window'
  if (state === 'closed') return 'Market closed — review is ready'
  return 'Checking today’s market state'
}

function MarketLifecycle({
  phase,
  marketState,
  clock,
  stale,
  onChange,
}: {
  phase: MarketPhase
  marketState: string
  clock: number | null
  stale: boolean
  onChange: (phase: MarketPhase) => void
}) {
  const stage = currentStage(marketState)
  return (
    <header className="market-phase-header">
      <nav className="phase-stepper" aria-label="Market day workflow">
        {PHASES.map((item, index) => {
          const temporal = index < stage ? 'complete' : index === stage ? 'now' : 'upcoming'
          return (
            <button
              key={item.id}
              className={`${temporal} ${phase === item.id ? 'selected' : ''}`}
              aria-current={phase === item.id ? 'step' : undefined}
              onClick={() => onChange(item.id)}
              title={item.hint}
            >
              <span className="phase-index" aria-hidden="true">{temporal === 'complete' ? '✓' : index + 1}</span>
              <span><strong>{item.label}</strong><small>{item.hint}</small></span>
            </button>
          )
        })}
      </nav>
      <div className={`market-freshness ${stale ? 'stale' : ''}`} role="status">
        <strong>{stale ? 'Data stale — retrying' : stateLabel(marketState)}</strong>
        <span>{clock ? `${ct.format(new Date(clock * 1000))} CT · 15-minute delayed SIP data` : 'Status refreshes automatically'}</span>
      </div>
    </header>
  )
}

function CollapsibleRail({ title, open, onToggle, children }: {
  title: string
  open: boolean
  onToggle: () => void
  children: ReactNode
}) {
  return (
    <aside className={`sim-rail ${open ? 'open' : ''}`} aria-label={title}>
      <button className="mobile-rail-toggle" aria-expanded={open} onClick={onToggle}>
        <span>{title}</span><span aria-hidden="true">{open ? '−' : '+'}</span>
      </button>
      <div className="sim-rail-content">{children}</div>
    </aside>
  )
}

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

export function MarketDayTab({
  phase,
  onPhaseChange,
}: {
  phase: MarketPhase
  onPhaseChange: (phase: MarketPhase) => void
}) {
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
  const [symbol, setSymbol] = useState(initialSymbol)
  const [tf, setTf] = useState<Timeframe>(initialTimeframe)
  const [replayError, setReplayError] = useState<string | null>(null)
  const [railOpen, setRailOpen] = useState(false)

  useEffect(() => replaceRouteQuery({ symbol, tf }), [symbol, tf])

  const md = mdQ.data
  useCalloutSound(md?.callouts ?? [])

  const replay = useReplaySession(tf)
  const inReplay = replay.session !== null
  const marketState = md?.market.state ?? symbolsQ.data?.state ?? 'unknown'
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

  const changePhase = (next: MarketPhase) => {
    if (inReplay) replay.exit()
    onPhaseChange(next)
  }

  const selectSymbol = (next: string) => {
    if (inReplay) replay.exit()
    setSymbol(next)
  }

  const startReplay = async (sym = symbol, day = displayDay, startAt?: number) => {
    if (!day) return
    setReplayError(null)
    try {
      await replay.start(sym, day, startAt)
      setRailOpen(true)
    } catch (error) {
      setReplayError(error instanceof Error ? error.message : String(error))
    }
  }

  const onReview = (sym: string, day: string, startAt: number) => {
    setSymbol(sym)
    onPhaseChange('trade')
    void startReplay(sym, day, startAt)
  }

  const act = async (id: string) => {
    await api.actOnCallout(id)
    await queryClient.invalidateQueries({ queryKey: ['marketday'] })
  }

  const lifecycle = (
    <MarketLifecycle
      phase={phase}
      marketState={marketState}
      clock={md?.session?.clock ?? null}
      stale={md?.poll.stale ?? false}
      onChange={changePhase}
    />
  )

  if (!inReplay && phase === 'plan') {
    return <div className="market-day">{lifecycle}<div className="md-takeover"><BriefingView /></div></div>
  }
  if (!inReplay && phase === 'review') {
    return <div className="market-day">{lifecycle}<div className="md-takeover"><RecapView onReview={onReview} /></div></div>
  }

  const showLiveRail = !inReplay && md?.session != null
  return (
    <div className="market-day">
      {lifecycle}
      <div className={`market-layout ${inReplay || showLiveRail ? 'replaying' : ''}`}>
        <WatchlistRail
          symbols={symbolsQ.data?.symbols ?? []}
          selected={symbol}
          onSelect={selectSymbol}
        />
        <section className="chart-area" aria-label={`${symbol} chart`}>
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
                {md?.poll.stale && (
                  <span className="stale-banner">
                    ⚠ stale{md.poll.stale_since ? ` since ${ct.format(new Date(md.poll.stale_since))}` : ''}
                  </span>
                )}
                {displayDay && (
                  <button className="btn-replay" onClick={() => void startReplay()}>
                    ▶ Replay this day
                  </button>
                )}
              </>
            )}
            {(replayError || (inReplay && sessionQ.error)) && (
              <span className="banner" role="alert">⚠ {replayError ?? String(sessionQ.error)}</span>
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
          <CollapsibleRail title="Practice controls" open={railOpen} onToggle={() => setRailOpen((value) => !value)}>
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
          </CollapsibleRail>
        )}
        {showLiveRail && md && (
          <CollapsibleRail title="Live coach" open={railOpen} onToggle={() => setRailOpen((value) => !value)}>
            {md.account && (
              <div className="acct-row">
                <span>Simulator equity <strong>${md.account.equity.toLocaleString()}</strong></span>
                {md.account.flattened && <span className="muted">flat (EOD)</span>}
              </div>
            )}
            {md.account?.positions.map((position) => (
              <div key={position.symbol} className={`pos-row ${position.unrealized >= 0 ? 'up' : 'down'}`}>
                <strong>{position.qty > 0 ? 'LONG' : 'SHORT'} {Math.abs(position.qty)} {position.symbol}</strong>
                <span className="pnl">{position.unrealized >= 0 ? '+' : ''}{position.unrealized.toFixed(2)}</span>
              </div>
            ))}
            {md.risk && (
              <div className="risk-panel">
                <div className="risk-head"><strong>Risk coach</strong><span className={`risk-mode ${md.risk.policy.mode}`}>{md.risk.policy.mode}</span></div>
                <div className="risk-usage"><span>P/L {md.risk.usage.closed_r.toFixed(2)}R</span><span>Trades {md.risk.usage.trades}/{md.risk.policy.max_trades_per_day}</span><span>Open {(md.risk.usage.open_risk_pct ?? 0).toFixed(2)}%</span></div>
                {md.risk.events.slice(0, 2).map((event, index) => <span key={`${event.ts}:${index}`} className={`risk-event ${event.disposition}`}>⚠ {event.detail}</span>)}
              </div>
            )}
            {!md.trading_unlocked && <div className="muted">Observe mode — trading unlocks after Module 9.</div>}
            <div className="callout-stack">
              {md.callouts.length === 0 && <div className="muted">No setups yet — the coach is watching.</div>}
              {md.callouts.map((callout) => (
                <CalloutCard key={callout.id} callout={callout} tradingUnlocked={md.trading_unlocked} onAct={act} />
              ))}
            </div>
          </CollapsibleRail>
        )}
      </div>
    </div>
  )
}
