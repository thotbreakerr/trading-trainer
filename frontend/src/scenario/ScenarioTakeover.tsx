import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { ScenarioResolution, Timeframe } from '../lib/types'
import { ChartErrorBoundary } from '../chart/ChartErrorBoundary'
import { ChartPane } from '../chart/ChartPane'
import { TimeframeSwitcher } from '../chart/TimeframeSwitcher'
import { ReplayControls } from '../replay/ReplayControls'
import { useReplaySession } from '../replay/useReplaySession'
import { OrderTicket } from '../sim/OrderTicket'
import { PositionPanel } from '../sim/PositionPanel'
import { useTakeoverA11y } from '../lib/useTakeoverA11y'

export function ScenarioTakeover({ id, onExit }: { id: string; onExit: () => void }) {
  const takeoverRef = useTakeoverA11y(onExit)
  const [tf, setTf] = useState<Timeframe>('5m')
  const [resolution, setResolution] = useState<ScenarioResolution | null>(null)
  const [error, setError] = useState<string | null>(null)
  const replay = useReplaySession(tf)
  const started = useRef(false)
  useEffect(() => {
    if (started.current) return
    started.current = true
    void api.startScenario(id).then((r) => replay.adopt(r.session)).catch((e) => setError(String(e)))
  }, [id, replay])
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
  const reveal = async () => {
    try {
      setResolution(await api.scenarioResolution(id))
      if (replay.playing) replay.playPause()
    } catch (e) { setError(String(e)) }
  }
  const close = () => { replay.exit(); onExit() }
  return (
    <div ref={takeoverRef} className="lesson-takeover" role="dialog" aria-modal="true" aria-label="Historical scenario" tabIndex={-1}>
      <header className="lesson-header">
        <button className="lesson-back" onClick={close}>← Learn</button>
        <span className="lesson-title">{resolution ? `${resolution.setup_type.replace(/_/g, ' ')} — ${resolution.symbol}` : 'Blind historical scenario'}</span>
      </header>
      <div className="lesson-chart">
        <div className="lesson-chart-bar">
          <span className="symbol">{replay.session?.symbols[0] ?? '—'}</span>
          {replay.session && <ReplayControls clock={replay.clock} playing={replay.playing} speed={replay.speed}
            done={replay.done} onPlayPause={replay.playPause} onStepOne={replay.stepOne}
            onSpeed={replay.setSpeed} onRestart={() => void replay.restart()} onExit={close} />}
          {error && <span className="banner">⚠ {error}</span>}
          <TimeframeSwitcher tf={tf} onChange={setTf} />
        </div>
        <ChartErrorBoundary><ChartPane bars={sessionQ.data?.bars ?? []} days={sessionQ.data?.days ?? []}
          overlays={sessionQ.data?.overlays} follow={replay.playing} fitKey={`scenario:${id}`} /></ChartErrorBoundary>
      </div>
      <div className="lesson-panel">
        <div className="practice-layout">
          <div className="scenario-prompt">
            {!resolution ? <>
              <h3>Trade the chart, not the answer</h3>
              <p className="muted">The setup, direction, fire time, and outcome stay hidden until you reveal them.</p>
              <button className="btn-primary" onClick={() => void reveal()}>Reveal scenario</button>
            </> : <>
              <h3>{resolution.direction.toUpperCase()} {resolution.setup_type.replace(/_/g, ' ')}</h3>
              <p>Fired {resolution.fired_et} ET · entry {resolution.entry.toFixed(2)} · stop {resolution.stop.toFixed(2)} · target {resolution.target.toFixed(2)}</p>
              <p className={resolution.outcome_r != null && resolution.outcome_r > 0 ? 'chg up' : 'chg down'}>
                Outcome: {resolution.outcome} {resolution.outcome_r == null ? '' : `(${resolution.outcome_r}R)`}
              </p>
              <p className="muted">Coach grade: {resolution.grade ?? 'ungraded'}</p>
            </>}
          </div>
          {replay.session && !resolution && <div className="practice-sim">
            <OrderTicket sessionId={replay.session.id} lastPrice={lastBar?.c ?? null} equity={accountQ.data?.equity ?? null} />
            <PositionPanel sessionId={replay.session.id} stepCount={replay.stepCount} events={replay.events} />
          </div>}
        </div>
      </div>
    </div>
  )
}
