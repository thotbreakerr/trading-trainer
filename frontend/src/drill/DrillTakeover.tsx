import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { Timeframe } from '../lib/types'
import { ChartErrorBoundary } from '../chart/ChartErrorBoundary'
import { ChartPane } from '../chart/ChartPane'
import { TimeframeSwitcher } from '../chart/TimeframeSwitcher'
import { OrderTicket } from '../sim/OrderTicket'
import { PositionPanel } from '../sim/PositionPanel'
import { ResolutionCard } from './ResolutionCard'
import { useDrillRun } from './useDrillRun'

const ct = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/Chicago',
  hour: 'numeric',
  minute: '2-digit',
})

const TALLY_ORDER = ['Textbook', 'Solid', 'Risky', 'Reckless', 'ungraded', 'passed']

/** Full-screen drill loop (doc-style takeover): blind replay of one setup
 * instance — trade it with the normal bracket flow or pass — then the reveal.
 * No restart, no seek: the first decision is the rep. */
export function DrillTakeover({
  setupKey,
  label,
  count,
  onExit,
}: {
  setupKey: string
  label: string
  count: number
  onExit: () => void
}) {
  const [tf, setTf] = useState<Timeframe>('5m')
  const drill = useDrillRun(setupKey, count, tf)
  const { replay } = drill
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true
    void drill.startRun()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const sessionQ = useQuery({
    queryKey: ['sessionBars', replay.session?.id ?? 'none', tf],
    queryFn: () => api.sessionBars(replay.session!.id, tf),
    enabled: !!replay.session,
    staleTime: 0,
  })
  const accountQ = useQuery({
    queryKey: ['account', replay.session?.id ?? 'none', replay.stepCount],
    queryFn: () => api.account(replay.session!.id),
    enabled: !!replay.session,
    staleTime: 0,
  })
  const lastBar = sessionQ.data?.bars[sessionQ.data.bars.length - 1]
  const acted =
    replay.events.length > 0 ||
    (accountQ.data?.working_orders.length ?? 0) > 0 ||
    (accountQ.data?.positions.length ?? 0) > 0

  const tallyChips = (
    <span className="drill-tally">
      {TALLY_ORDER.filter((k) => drill.tally[k]).map((k) => (
        <span key={k} className={`drill-chip ${k.toLowerCase()}`}>
          {k === 'passed' ? 'passed' : k} ×{drill.tally[k]}
        </span>
      ))}
    </span>
  )

  if (drill.empty) {
    return (
      <div className="lesson-takeover">
        <header className="lesson-header">
          <button className="lesson-back" onClick={onExit}>
            ← Learn
          </button>
          <span className="lesson-title">Drill: {label}</span>
        </header>
        <div className="lesson-panel">
          <p className="muted">
            No fresh {label} instances in the cache right now — every discovered instance has
            already been drilled, or the cache needs more complete days (Market Day keeps
            adding them).
          </p>
          <button className="btn-primary" onClick={onExit}>
            Back to Learn
          </button>
        </div>
      </div>
    )
  }

  if (drill.phase === 'summary') {
    return (
      <div className="lesson-takeover">
        <header className="lesson-header">
          <button className="lesson-back" onClick={onExit}>
            ← Learn
          </button>
          <span className="lesson-title">Drill complete: {label}</span>
        </header>
        <div className="lesson-panel">
          <h3>
            {drill.total} instance{drill.total === 1 ? '' : 's'} drilled
          </h3>
          <p>{tallyChips}</p>
          <p className="muted">
            Grades and outcomes are in the Journal (drill filter). Passed setups count too —
            knowing when NOT to trade is half the skill.
          </p>
          <div className="actions">
            <button className="btn-primary" onClick={() => void drill.startRun()}>
              Drill again
            </button>
            <button onClick={onExit}>Back to Learn</button>
          </div>
        </div>
      </div>
    )
  }

  const clockLabel =
    replay.clock != null ? `${ct.format(new Date(replay.clock * 1000))} CT` : null

  return (
    <div className="lesson-takeover">
      <header className="lesson-header">
        <button className="lesson-back" onClick={onExit}>
          ← Learn
        </button>
        <span className="lesson-title">
          Drill: {label} — instance {drill.idx + 1} of {drill.total}
        </span>
        {tallyChips}
      </header>

      <div className="lesson-chart">
        <div className="lesson-chart-bar">
          <span className="symbol">{replay.session?.symbols[0] ?? '—'}</span>
          {replay.session && <span className="lesson-day">{replay.session.day}</span>}
          {clockLabel && <span className="replay-clock">{clockLabel}</span>}
          {replay.session && drill.phase === 'live' && (
            <span className="lesson-replay-controls">
              <button onClick={replay.playPause}>{replay.playing ? '⏸' : '▶'}</button>
              <button onClick={replay.stepOne} disabled={replay.playing}>
                +1
              </button>
              {[1, 2, 5].map((s) => (
                <button
                  key={s}
                  className={replay.speed === s ? 'active' : ''}
                  onClick={() => replay.setSpeed(s as 1 | 2 | 5)}
                >
                  {s}×
                </button>
              ))}
            </span>
          )}
          {drill.error && <span className="banner">⚠ {drill.error}</span>}
          <TimeframeSwitcher tf={tf} onChange={setTf} />
        </div>
        <ChartErrorBoundary>
          <ChartPane
            bars={sessionQ.data?.bars ?? []}
            days={sessionQ.data?.days ?? []}
            overlays={sessionQ.data?.overlays}
            follow={replay.playing}
            fitKey={`drill:${replay.session?.id ?? 'none'}`}
          />
        </ChartErrorBoundary>
      </div>

      <div className="lesson-panel">
        {drill.phase === 'live' && (
          <div className="practice-layout">
            <div className="practice-goal">
              <h4>Somewhere ahead, a {label.toLowerCase()} fires</h4>
              <p className="muted">
                Step or play forward. Trade it with a bracket when YOU would — or pass. The
                first bracket is your graded rep; the reveal shows what the setup really did.
              </p>
              <div className="actions">
                <button
                  className="btn-primary"
                  disabled={drill.busy}
                  onClick={() => void drill.resolve()}
                >
                  {acted ? 'Show resolution' : 'Pass — show resolution'}
                </button>
              </div>
            </div>
            {replay.session && (
              <div className="practice-sim">
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
              </div>
            )}
          </div>
        )}
        {drill.phase === 'resolved' && drill.resolution && (
          <div className="drill-resolved">
            <ResolutionCard r={drill.resolution} />
            <div className="actions">
              <button
                className="btn-primary"
                disabled={drill.busy}
                onClick={() => void drill.nextInstance()}
              >
                {drill.idx + 1 < drill.total ? 'Next instance →' : 'Finish drill ✓'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
