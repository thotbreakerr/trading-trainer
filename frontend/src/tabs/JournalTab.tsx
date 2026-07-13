import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { JournalTradeDetail, Timeframe, TradeReview } from '../lib/types'
import { ChartErrorBoundary } from '../chart/ChartErrorBoundary'
import { ChartPane } from '../chart/ChartPane'
import { TimeframeSwitcher } from '../chart/TimeframeSwitcher'
import { GradeDistributionChart, EquityCurve } from '../journal/TrajectoryCharts'
import { ReplayControls } from '../replay/ReplayControls'
import { useReplaySession } from '../replay/useReplaySession'
import { EmptyState, ErrorState, LoadingState } from '../shell/AsyncState'
import { useTakeoverA11y } from '../lib/useTakeoverA11y'

function fmtR(v: number | null): string {
  if (v == null) return '—'
  return `${v > 0 ? '+' : ''}${v}R`
}

function pct(v: number | null): string {
  return v == null ? '—' : `${Math.round(v * 100)}%`
}

function ReviewEditor({ trade, onClose }: { trade: JournalTradeDetail; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState<TradeReview>(trade.review)
  useEffect(() => setForm(trade.review), [trade])
  const save = useMutation({
    mutationFn: () => {
      const { updated_at: _updatedAt, ...body } = form
      return api.saveTradeReview(trade.id, body)
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['journalTrade', trade.id] }),
        queryClient.invalidateQueries({ queryKey: ['journalTrades'] }),
      ])
    },
  })
  const setList = (key: 'tags' | 'mistakes', value: string) =>
    setForm((f) => ({ ...f, [key]: value.split(',').map((x) => x.trim()).filter(Boolean) }))

  return (
    <section className="review-workspace">
      <div className="review-head">
        <div>
          <h3>{trade.symbol} decision review</h3>
          <span className="muted">{trade.setup_type?.replace(/_/g, ' ') ?? 'Unclassified setup'}</span>
        </div>
        <label className="review-check">
          <input
            type="checkbox"
            checked={form.reviewed}
            onChange={(e) => setForm({ ...form, reviewed: e.target.checked })}
          />
          reviewed
        </label>
        <button className="review-close" aria-label="Close trade review" onClick={onClose}>×</button>
      </div>
      <div className="review-metrics">
        <span><small>MFE</small><strong>{fmtR(trade.metrics.mfe_r)}</strong></span>
        <span><small>MAE</small><strong>{fmtR(trade.metrics.mae_r)}</strong></span>
        <span><small>available</small><strong>{fmtR(trade.metrics.available_r)}</strong></span>
        <span><small>entry eff.</small><strong>{pct(trade.metrics.entry_efficiency)}</strong></span>
        <span><small>exit eff.</small><strong>{pct(trade.metrics.exit_efficiency)}</strong></span>
        <span><small>duration</small><strong>{trade.metrics.duration_minutes ?? '—'} min</strong></span>
      </div>
      <div className="review-form">
        <label>Thesis<textarea value={form.thesis} onChange={(e) => setForm({ ...form, thesis: e.target.value })} /></label>
        <label>Post-trade notes<textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></label>
        <label>Confidence
          <select value={form.confidence ?? ''} onChange={(e) => setForm({ ...form, confidence: e.target.value ? Number(e.target.value) : null })}>
            <option value="">—</option>{[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <label>Emotion<input value={form.emotion} onChange={(e) => setForm({ ...form, emotion: e.target.value })} placeholder="calm, rushed, FOMO…" /></label>
        <label>Mistakes<input value={form.mistakes.join(', ')} onChange={(e) => setList('mistakes', e.target.value)} placeholder="late entry, moved stop" /></label>
        <label>Tags<input value={form.tags.join(', ')} onChange={(e) => setList('tags', e.target.value)} placeholder="A+, opening drive" /></label>
      </div>
      <div className="actions">
        <button className="btn-primary" disabled={save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? 'Saving…' : 'Save review'}
        </button>
        {save.isError && <span className="banner">⚠ {String(save.error)}</span>}
        {save.isSuccess && <span className="save-success" role="status">✓ Review saved</span>}
      </div>
    </section>
  )
}

export function JournalTab({
  selectedTradeId,
  onSelectTrade,
  onPractice,
}: {
  selectedTradeId: number | null
  onSelectTrade: (id: number | null) => void
  onPractice: () => void
}) {
  const [mode, setMode] = useState<'all' | 'practice' | 'marketday' | 'drill' | 'scenario'>('all')
  const [tf, setTf] = useState<Timeframe>('5m')
  const [symbol, setSymbol] = useState('')
  const [grade, setGrade] = useState('')
  const [tag, setTag] = useState('')
  const [reviewed, setReviewed] = useState<'all' | 'true' | 'false'>('all')
  const selectedId = selectedTradeId
  const filters = {
    mode: mode === 'all' ? undefined : mode,
    symbol: symbol || undefined,
    grade: grade || undefined,
    tag: tag || undefined,
    reviewed: reviewed === 'all' ? undefined : reviewed === 'true',
  }
  const tradesQ = useQuery({ queryKey: ['journalTrades', filters], queryFn: () => api.journalTrades(filters) })
  const statsQ = useQuery({ queryKey: ['journalStats', mode], queryFn: () => api.journalStats(filters.mode) })
  const detailQ = useQuery({
    queryKey: ['journalTrade', selectedId ?? 0],
    queryFn: () => api.journalTrade(selectedId!),
    enabled: selectedId != null,
  })
  const replay = useReplaySession(tf)
  const takeoverRef = useTakeoverA11y(replay.exit, replay.session !== null)
  const sessionQ = useQuery({
    queryKey: ['sessionBars', replay.session?.id ?? 'none', tf],
    queryFn: () => api.sessionBars(replay.session!.id, tf),
    enabled: !!replay.session,
    staleTime: 0,
  })
  const stats = statsQ.data
  const cum = stats?.cumulative
  const hasFilters = mode !== 'all' || symbol !== '' || grade !== '' || tag !== '' || reviewed !== 'all'
  const clearFilters = () => {
    setMode('all')
    setSymbol('')
    setGrade('')
    setTag('')
    setReviewed('all')
  }

  if (replay.session) {
    return (
      <div ref={takeoverRef} className="lesson-takeover" role="dialog" aria-modal="true" aria-label="Trade tape review" tabIndex={-1}>
        <header className="lesson-header">
          <button className="lesson-back" onClick={replay.exit}>← Journal</button>
          <span className="lesson-title">Reviewing {replay.session.symbols[0]} — {replay.session.day}</span>
        </header>
        <div className="lesson-chart" style={{ gridRow: '2 / 4' }}>
          <div className="lesson-chart-bar">
            <span className="symbol">{replay.session.symbols[0]}</span>
            <ReplayControls clock={replay.clock} playing={replay.playing} speed={replay.speed} done={replay.done}
              onPlayPause={replay.playPause} onStepOne={replay.stepOne} onSpeed={replay.setSpeed}
              onRestart={() => void replay.restart()} onExit={replay.exit} />
            <TimeframeSwitcher tf={tf} onChange={setTf} />
          </div>
          <ChartErrorBoundary>
            <ChartPane bars={sessionQ.data?.bars ?? []} days={sessionQ.data?.days ?? []}
              overlays={sessionQ.data?.overlays} markers={detailQ.data?.metrics.markers}
              follow={replay.playing} fitKey={`review:${replay.session.id}`} />
          </ChartErrorBoundary>
        </div>
      </div>
    )
  }

  return (
    <div className="stub journal">
      <div className="view-head"><h2>Journal</h2>
        <div className="view-chips">
          {(['all', 'practice', 'marketday', 'drill', 'scenario'] as const).map((m) => (
            <button key={m} className={mode === m ? 'active' : ''} aria-pressed={mode === m} onClick={() => setMode(m)}>{m === 'marketday' ? 'market day' : m}</button>
          ))}
        </div>
      </div>
      <div className="journal-filters" aria-label="Trade filters">
        <label><span className="sr-only">Filter by symbol</span><input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} placeholder="Symbol" /></label>
        <label><span className="sr-only">Filter by grade</span><select value={grade} onChange={(e) => setGrade(e.target.value)}><option value="">All grades</option>{['Textbook', 'Solid', 'Risky', 'Reckless'].map((g) => <option key={g}>{g}</option>)}</select></label>
        <label><span className="sr-only">Filter by tag</span><input value={tag} onChange={(e) => setTag(e.target.value)} placeholder="Tag" /></label>
        <label><span className="sr-only">Filter by review status</span><select value={reviewed} onChange={(e) => setReviewed(e.target.value as typeof reviewed)}><option value="all">All reviews</option><option value="true">Reviewed</option><option value="false">Needs review</option></select></label>
        {hasFilters && <button className="btn-quiet" onClick={clearFilters}>Clear filters</button>}
      </div>
      <div className="stat-cards">
        <div className="stat-card"><span className="muted">trades</span><strong>{cum?.trades ?? 0}</strong></div>
        <div className="stat-card"><span className="muted">win rate</span><strong>{cum?.win_rate != null ? `${Math.round((cum.win_rate as number) * 100)}%` : '—'}</strong></div>
        <div className="stat-card"><span className="muted">expectancy</span><strong>{fmtR((cum?.expectancy_r as number | null) ?? null)}</strong></div>
        <div className="stat-card"><span className="muted">total</span><strong>{fmtR((cum?.total_r as number | null) ?? null)}</strong></div>
        <div className="stat-card"><span className="muted">rolling 20 exp.</span><strong>{fmtR((stats?.rolling_20.expectancy_r as number | null) ?? null)}</strong></div>
      </div>
      {statsQ.isPending && <LoadingState label="Loading performance trends" />}
      {statsQ.isError && <ErrorState title="Could not load performance trends" error={statsQ.error} onRetry={() => void statsQ.refetch()} />}
      {stats && <><h3>Grade distribution over time</h3><GradeDistributionChart data={stats} /><h3>Equity curve (R)</h3><EquityCurve data={stats} /></>}
      <h3>Trades</h3>
      {tradesQ.isPending && <LoadingState label="Loading journal trades" />}
      {tradesQ.isError && <ErrorState title="Could not load journal trades" error={tradesQ.error} onRetry={() => void tradesQ.refetch()} />}
      {tradesQ.data?.trades.length === 0 && <EmptyState title={hasFilters ? 'No trades match these filters' : 'Your journal is ready for the first decision'} body={hasFilters ? 'Clear or broaden the filters to find a trade.' : 'Complete a replay, drill, or market-day trade and it will appear here for review.'} action={<button className="btn-replay" onClick={hasFilters ? clearFilters : onPractice}>{hasFilters ? 'Clear filters' : 'Start a practice drill'}</button>} />}
      {!!tradesQ.data?.trades.length && (
        <div className="table-scroll"><table className="recap-table"><thead><tr><th>entry (ET)</th><th>mode</th><th>symbol</th><th>setup</th><th>R</th><th>grade</th><th>review</th><th></th></tr></thead>
          <tbody>{tradesQ.data.trades.map((t) => (
            <tr key={t.id} className={selectedId === t.id ? 'selected' : ''}>
              <td>{t.entry_et}</td><td>{t.mode}</td><td>{t.symbol}</td><td>{t.setup_type?.replace(/_/g, ' ') ?? '—'}</td>
              <td className={`chg ${t.r_multiple != null && t.r_multiple > 0 ? 'up' : 'down'}`}>{fmtR(t.r_multiple)}</td>
              <td>{t.grade ?? '—'}</td><td>{t.review.reviewed ? '✓' : 'open'}</td>
              <td><div className="table-actions"><button className="btn-quiet" aria-label={`Open ${t.symbol} trade review`} onClick={() => onSelectTrade(t.id)}>Open</button><button className="btn-replay" onClick={() => { onSelectTrade(t.id); void replay.start(t.replay.symbol, t.replay.day, t.replay.start_at) }}>▶ Tape</button></div></td>
            </tr>
          ))}</tbody></table></div>
      )}
      {detailQ.isPending && selectedId != null && <LoadingState label="Loading trade review" />}
      {detailQ.isError && <ErrorState title="Could not load this trade" error={detailQ.error} onRetry={() => void detailQ.refetch()} />}
      {detailQ.data && <ReviewEditor trade={detailQ.data} onClose={() => onSelectTrade(null)} />}
    </div>
  )
}
