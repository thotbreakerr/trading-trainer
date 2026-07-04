import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { Timeframe } from '../lib/types'
import { ChartErrorBoundary } from '../chart/ChartErrorBoundary'
import { ChartPane } from '../chart/ChartPane'
import { TimeframeSwitcher } from '../chart/TimeframeSwitcher'
import { GradeDistributionChart, EquityCurve } from '../journal/TrajectoryCharts'
import { ReplayControls } from '../replay/ReplayControls'
import { useReplaySession } from '../replay/useReplaySession'

function fmtR(v: number | null): string {
  if (v == null) return '—'
  return `${v > 0 ? '+' : ''}${v}R`
}

export function JournalTab() {
  const [mode, setMode] = useState<'all' | 'practice' | 'marketday'>('all')
  const [tf, setTf] = useState<Timeframe>('5m')
  const modeParam = mode === 'all' ? undefined : mode
  const tradesQ = useQuery({
    queryKey: ['journalTrades', mode],
    queryFn: () => api.journalTrades(modeParam),
  })
  const statsQ = useQuery({
    queryKey: ['journalStats', mode],
    queryFn: () => api.journalStats(modeParam),
  })
  const replay = useReplaySession()
  const sessionQ = useQuery({
    queryKey: ['sessionBars', replay.session?.id ?? 'none', tf],
    queryFn: () => api.sessionBars(replay.session!.id, tf),
    enabled: !!replay.session,
    staleTime: 0,
  })

  const stats = statsQ.data
  const cum = stats?.cumulative

  if (replay.session) {
    // self-contained review takeover: the journal row, replayed (doc §11)
    return (
      <div className="lesson-takeover">
        <header className="lesson-header">
          <button className="lesson-back" onClick={replay.exit}>
            ← Journal
          </button>
          <span className="lesson-title">
            Reviewing {replay.session.symbols[0]} — {replay.session.day}
          </span>
        </header>
        <div className="lesson-chart" style={{ gridRow: '2 / 4' }}>
          <div className="lesson-chart-bar">
            <span className="symbol">{replay.session.symbols[0]}</span>
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
            <TimeframeSwitcher tf={tf} onChange={setTf} />
          </div>
          <ChartErrorBoundary>
            <ChartPane
              bars={sessionQ.data?.bars ?? []}
              days={sessionQ.data?.days ?? []}
              overlays={sessionQ.data?.overlays}
              follow={replay.playing}
              fitKey={`review:${replay.session.id}`}
            />
          </ChartErrorBoundary>
        </div>
      </div>
    )
  }

  return (
    <div className="stub journal">
      <div className="view-head">
        <h2>Journal</h2>
        <div className="view-chips">
          {(['all', 'practice', 'marketday'] as const).map((m) => (
            <button key={m} className={mode === m ? 'active' : ''} onClick={() => setMode(m)}>
              {m === 'marketday' ? 'market day' : m}
            </button>
          ))}
        </div>
      </div>

      <div className="stat-cards">
        <div className="stat-card">
          <span className="muted">trades</span>
          <strong>{cum?.trades ?? 0}</strong>
        </div>
        <div className="stat-card">
          <span className="muted">win rate</span>
          <strong>{cum?.win_rate != null ? `${Math.round((cum.win_rate as number) * 100)}%` : '—'}</strong>
        </div>
        <div className="stat-card">
          <span className="muted">expectancy</span>
          <strong>{fmtR((cum?.expectancy_r as number | null) ?? null)}</strong>
        </div>
        <div className="stat-card">
          <span className="muted">total</span>
          <strong>{fmtR((cum?.total_r as number | null) ?? null)}</strong>
        </div>
        <div className="stat-card">
          <span className="muted">rolling 20 exp.</span>
          <strong>{fmtR((stats?.rolling_20.expectancy_r as number | null) ?? null)}</strong>
        </div>
      </div>

      <h3>Grade distribution over time</h3>
      {stats && <GradeDistributionChart data={stats} />}
      <h3>Equity curve (R)</h3>
      {stats && <EquityCurve data={stats} />}

      <h3>Trades</h3>
      {tradesQ.data && tradesQ.data.trades.length === 0 && (
        <p className="muted">
          Nothing here yet — practice trades (Module 8 on) and Market Day trades all land here.
        </p>
      )}
      {tradesQ.data && tradesQ.data.trades.length > 0 && (
        <table className="recap-table">
          <thead>
            <tr>
              <th>entry (ET)</th><th>mode</th><th>symbol</th><th>dir</th><th>qty</th>
              <th>entry</th><th>exit</th><th>R</th><th>grade</th><th></th>
            </tr>
          </thead>
          <tbody>
            {tradesQ.data.trades.map((t, i) => (
              <tr key={i}>
                <td>{t.entry_et}</td>
                <td>{t.mode}</td>
                <td>{t.symbol}</td>
                <td>{t.direction}</td>
                <td>{t.qty}</td>
                <td>{t.entry_price.toFixed(2)}</td>
                <td>
                  {t.exit_price?.toFixed(2) ?? '—'} ({t.exit_reason ?? 'open'})
                </td>
                <td className={`chg ${t.r_multiple != null && t.r_multiple > 0 ? 'up' : 'down'}`}>
                  {fmtR(t.r_multiple)}
                </td>
                <td>{t.grade ?? '—'}</td>
                <td>
                  <button
                    className="btn-replay"
                    onClick={() => void replay.start(t.review.symbol, t.review.day, t.review.start_at)}
                  >
                    ▶ Review
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
