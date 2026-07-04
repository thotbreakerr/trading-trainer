import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { GradeInfo, SizingResult } from '../lib/types'

/** Bracket-first order entry (doc §9): entry + stop + target as one unit,
 * sized by the risk calculator unless the user overrides the share count. */
export function OrderTicket({
  sessionId,
  lastPrice,
  equity,
}: {
  sessionId: string
  lastPrice: number | null
  equity: number | null
}) {
  const queryClient = useQueryClient()
  const [side, setSide] = useState<'buy' | 'sell'>('buy')
  const [entryType, setEntryType] = useState<'market' | 'limit'>('market')
  const [limitPrice, setLimitPrice] = useState('')
  const [stopPrice, setStopPrice] = useState('')
  const [targetPrice, setTargetPrice] = useState('')
  const [riskPct, setRiskPct] = useState('1.0')
  const [qtyOverride, setQtyOverride] = useState('')
  const [sizing, setSizing] = useState<SizingResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [grade, setGrade] = useState<GradeInfo | null>(null)
  const [busy, setBusy] = useState(false)

  const entryRef = entryType === 'limit' ? parseFloat(limitPrice) : (lastPrice ?? NaN)
  const stop = parseFloat(stopPrice)
  const risk = parseFloat(riskPct)

  useEffect(() => {
    setSizing(null)
    if (!equity || !isFinite(entryRef) || !isFinite(stop) || !isFinite(risk) || qtyOverride) return
    const t = window.setTimeout(() => {
      api
        .sizing({ equity, entry: entryRef, stop, risk_pct: risk })
        .then(setSizing)
        .catch(() => setSizing(null))
    }, 250)
    return () => window.clearTimeout(t)
  }, [equity, entryRef, stop, risk, qtyOverride])

  const place = async () => {
    setBusy(true)
    setError(null)
    setGrade(null)
    try {
      const result = await api.placeOrder(sessionId, {
        kind: 'bracket',
        side,
        entry_type: entryType,
        limit_price: entryType === 'limit' ? parseFloat(limitPrice) : undefined,
        stop_price: parseFloat(stopPrice),
        target_price: parseFloat(targetPrice),
        risk_pct: isFinite(risk) ? risk : undefined,
        qty: qtyOverride ? parseInt(qtyOverride, 10) : undefined,
      })
      if (result.rejected) setError(result.reason ?? 'rejected')
      setGrade(result.grade)
      await queryClient.invalidateQueries({ queryKey: ['account', sessionId] })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const ready =
    isFinite(stop) && isFinite(parseFloat(targetPrice)) && (entryType === 'market' || isFinite(parseFloat(limitPrice)))

  return (
    <div className="ticket">
      <div className="ticket-title">Bracket order</div>
      <div className="ticket-row side-row">
        <button className={`side buy ${side === 'buy' ? 'active' : ''}`} onClick={() => setSide('buy')}>
          Long
        </button>
        <button className={`side sell ${side === 'sell' ? 'active' : ''}`} onClick={() => setSide('sell')}>
          Short
        </button>
      </div>
      <div className="ticket-row">
        <label>Entry</label>
        <select value={entryType} onChange={(e) => setEntryType(e.target.value as 'market' | 'limit')}>
          <option value="market">Market (next open)</option>
          <option value="limit">Limit</option>
        </select>
        {entryType === 'limit' ? (
          <input placeholder="price" value={limitPrice} onChange={(e) => setLimitPrice(e.target.value)} />
        ) : (
          <span className="ref-price">{lastPrice != null ? `~${lastPrice.toFixed(2)}` : '—'}</span>
        )}
      </div>
      <div className="ticket-row">
        <label>Stop</label>
        <input placeholder="price" value={stopPrice} onChange={(e) => setStopPrice(e.target.value)} />
        <label>Target</label>
        <input placeholder="price" value={targetPrice} onChange={(e) => setTargetPrice(e.target.value)} />
      </div>
      <div className="ticket-row">
        <label>Risk %</label>
        <input value={riskPct} onChange={(e) => setRiskPct(e.target.value)} />
        <label>Qty</label>
        <input placeholder="auto" value={qtyOverride} onChange={(e) => setQtyOverride(e.target.value)} />
      </div>
      {sizing && !qtyOverride && (
        <div className="sizing-note">
          {sizing.shares} shares · risking ${sizing.risk_amount.toFixed(0)} (
          {sizing.per_share_risk.toFixed(2)}/sh){sizing.bp_capped ? ' · BP-capped' : ''}
        </div>
      )}
      {error && <div className="ticket-error">{error}</div>}
      <button className="btn-primary place" disabled={!ready || busy} onClick={() => void place()}>
        Place {side === 'buy' ? 'long' : 'short'} bracket
      </button>
      {grade && (
        <div className={`grade-card ${grade.tier.toLowerCase()}`}>
          <div className="grade-tier">{grade.tier}</div>
          {grade.note && <div className="grade-note">{grade.note}</div>}
          <ul className="grade-checklist">
            {grade.checklist.map((c) => (
              <li key={c.key} className={c.passed ? 'pass' : 'fail'} title={c.detail}>
                {c.passed ? '✓' : '✗'} {c.label}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
