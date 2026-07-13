import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { BriefingPrediction } from '../lib/types'

function PredictionCard({ day, symbol, prediction, marketLocked }: {
  day: string
  symbol: string
  prediction?: BriefingPrediction
  marketLocked: boolean
}) {
  const queryClient = useQueryClient()
  const [direction, setDirection] = useState(prediction?.direction ?? 'neutral')
  const [keyLevel, setKeyLevel] = useState(prediction?.key_level?.toString() ?? '')
  const [setup, setSetup] = useState(prediction?.setup ?? '')
  const [invalidation, setInvalidation] = useState(prediction?.invalidation ?? '')
  const [confidence, setConfidence] = useState(prediction?.confidence ?? 3)
  const locked = Boolean(prediction && marketLocked)
  const save = useMutation({
    mutationFn: () => api.savePrediction({ day, symbol, direction, key_level: keyLevel ? Number(keyLevel) : null, setup, invalidation, confidence }),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['predictions', day] }),
  })
  const score = prediction?.score
  return <article className={`prediction-card ${locked ? 'locked' : ''}`}>
    <div className="prediction-head"><strong>{symbol}</strong>
      {prediction?.is_late ? <span className="prediction-late">late · not scored</span> : locked ? <span className="muted">🔒 locked at open</span> : marketLocked ? <span className="prediction-late">late plan</span> : <span className="muted">editable until open</span>}
    </div>
    <div className="prediction-form">
      <label>Bias<select disabled={locked} value={direction} onChange={(e) => setDirection(e.target.value as typeof direction)}><option value="bullish">Bullish</option><option value="bearish">Bearish</option><option value="neutral">Neutral</option></select></label>
      <label>Confidence<select disabled={locked} value={confidence} onChange={(e) => setConfidence(Number(e.target.value))}>{[1, 2, 3, 4, 5].map((n) => <option key={n}>{n}</option>)}</select></label>
      <label>Key level<input disabled={locked} type="number" step="0.01" value={keyLevel} onChange={(e) => setKeyLevel(e.target.value)} /></label>
      <label>Expected setup<input disabled={locked} value={setup} onChange={(e) => setSetup(e.target.value)} placeholder="ORB, VWAP reclaim…" /></label>
      <label className="prediction-wide">Invalidation<input disabled={locked} value={invalidation} onChange={(e) => setInvalidation(e.target.value)} placeholder="What proves this plan wrong?" /></label>
    </div>
    {!locked && <button className="btn-primary" disabled={save.isPending} onClick={() => save.mutate()}>{prediction ? 'Update plan' : marketLocked ? 'Save late plan' : 'Commit plan'}</button>}
    {save.isError && <span className="banner">⚠ {String(save.error)}</span>}
    {score?.status === 'scored' && <div className="prediction-score"><strong>{score.total}/100</strong><span>{score.direction_correct ? 'direction ✓' : `actual ${score.actual_direction}`} · {score.level_hit ? 'level touched ✓' : 'level missed'} · calibration {score.brier}</span></div>}
    {score?.status === 'pending_data' && locked && <span className="muted">Score appears after complete session data is cached.</span>}
  </article>
}

export function PredictionPanel({ day, symbols }: { day: string; symbols: string[] }) {
  const predictionsQ = useQuery({ queryKey: ['predictions', day], queryFn: () => api.predictions(day) })
  if (predictionsQ.isPending) return <section className="prediction-panel"><p className="muted">Loading plan commitments…</p></section>
  if (predictionsQ.isError) return <section className="prediction-panel"><p className="banner">⚠ {String(predictionsQ.error)}</p></section>
  const data = predictionsQ.data
  const bySymbol = new Map(data.predictions.map((prediction) => [prediction.symbol, prediction]))
  return <section className="prediction-panel">
    <div><h3>Pre-market commitments</h3><p className="muted">Write the thesis before the tape answers. Confidence is scored for calibration, not bravado.</p></div>
    <div className="prediction-grid">{symbols.map((symbol) => <PredictionCard key={`${symbol}:${bySymbol.get(symbol)?.updated_at ?? 'new'}`} day={day} symbol={symbol} prediction={bySymbol.get(symbol)} marketLocked={data.locked} />)}</div>
  </section>
}
