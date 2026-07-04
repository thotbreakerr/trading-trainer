import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { BriefingCard } from '../lib/types'

function fmt(v: number | null | undefined, digits = 2): string {
  return v == null ? '—' : v.toFixed(digits)
}

function Card({ card }: { card: BriefingCard }) {
  const gap = card.gap_pct
  return (
    <div className="brief-card">
      <div className="brief-head">
        <strong>{card.symbol}</strong>
        <span className={`chg ${gap != null && gap < 0 ? 'down' : 'up'}`}>
          {gap != null ? `${gap >= 0 ? '+' : ''}${gap.toFixed(2)}% gap` : '—'}
        </span>
      </div>
      <div className="brief-grid">
        <span>PM RVOL</span>
        <span>{fmt(card.premarket_rvol, 1)}</span>
        <span>PM H/L</span>
        <span>
          {fmt(card.premarket_high)} / {fmt(card.premarket_low)}
        </span>
        <span>PD H/L/C</span>
        <span>
          {fmt(card.prior_high)} / {fmt(card.prior_low)} / {fmt(card.prior_close)}
        </span>
        <span>Nearest level</span>
        <span>
          {card.nearest_level
            ? `${card.nearest_level.name} ${card.nearest_level.price.toFixed(2)} (${card.nearest_level.distance_pct}%)`
            : '—'}
        </span>
        <span>Daily trend</span>
        <span>{card.daily_trend ?? '—'}</span>
      </div>
    </div>
  )
}

export function BriefingView() {
  const queryClient = useQueryClient()
  const briefingQ = useQuery({ queryKey: ['briefing'], queryFn: () => api.briefing() })
  const briefing = briefingQ.data

  if (briefingQ.isPending) return <div className="boot">Building the briefing…</div>
  if (briefingQ.isError) return <div className="boot error">⚠ {String(briefingQ.error)}</div>
  if (!briefing) return null

  const times = briefing.game_plan.key_times
  const timeRow = (label: string, key: string) =>
    times[key] ? (
      <div className="time-row" key={key}>
        <span>{label}</span>
        <strong>{times[key].ct} CT</strong>
        <span className="muted">({times[key].et} ET)</span>
      </div>
    ) : null

  return (
    <div className="briefing">
      <div className="view-head">
        <h2>Morning briefing — {briefing.day}</h2>
        {briefing.half_day && <span className="banner">Half day — early close</span>}
        <button
          className="btn-replay"
          onClick={() =>
            void api.briefing(true).then(() => queryClient.invalidateQueries({ queryKey: ['briefing'] }))
          }
        >
          ↻ refresh view
        </button>
      </div>
      <div className="brief-cards">
        {briefing.cards.map((c) => (
          <Card key={c.symbol} card={c} />
        ))}
      </div>
      <div className="brief-columns">
        <div className="focus-list">
          <h3>Focus list</h3>
          {briefing.focus.map((f) => (
            <div key={f.symbol} className="focus-row">
              <strong>{f.symbol}</strong> — {f.why}
            </div>
          ))}
        </div>
        <div className="game-plan">
          <h3>Game plan</h3>
          <div className="muted">
            Setups in play:{' '}
            {briefing.game_plan.setups_in_play.length
              ? briefing.game_plan.setups_in_play.join(', ').replace(/_/g, ' ')
              : 'none unlocked yet — observe mode'}
          </div>
          {timeRow('Open', 'open')}
          {timeRow('Opening range complete', 'or_complete')}
          {timeRow('Reversal window', 'reversal_window')}
          {timeRow('Flatten warning', 'flatten_warning')}
          {timeRow('Close', 'close')}
          <p className="muted">{briefing.game_plan.note}</p>
        </div>
      </div>
    </div>
  )
}
