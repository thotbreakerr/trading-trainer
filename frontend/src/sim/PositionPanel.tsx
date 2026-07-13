import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { SimEvent } from '../lib/types'

export function PositionPanel({
  sessionId,
  stepCount,
  events,
}: {
  sessionId: string
  stepCount: number // bump to refetch after steps
  events: SimEvent[]
}) {
  const queryClient = useQueryClient()
  const accountQ = useQuery({
    queryKey: ['account', sessionId, stepCount],
    queryFn: () => api.account(sessionId),
    staleTime: 0,
  })
  const account = accountQ.data
  const riskQ = useQuery({
    queryKey: ['risk', sessionId, stepCount],
    queryFn: () => api.riskStatus(sessionId),
    staleTime: 0,
  })
  const risk = riskQ.data
  const cancel = async (orderId: number) => {
    await api.cancelOrder(sessionId, orderId)
    await queryClient.invalidateQueries({ queryKey: ['account', sessionId] })
  }

  return (
    <div className="position-panel">
      {account && (
        <div className="acct-row">
          <span>
            Equity <strong>${account.equity.toLocaleString()}</strong>
          </span>
          <span className="muted">BP ${Math.max(account.buying_power_left, 0).toLocaleString()}</span>
        </div>
      )}
      {risk && <div className="risk-panel">
        <div className="risk-head"><strong>Risk coach</strong><span className={`risk-mode ${risk.policy.mode}`}>{risk.policy.mode}</span></div>
        <div className="risk-usage"><span>P/L {risk.usage.closed_r.toFixed(2)}R / -{risk.policy.max_daily_loss_r}R</span><span>Trades {risk.usage.trades}/{risk.policy.max_trades_per_day}</span><span>Open risk {(risk.usage.open_risk_pct ?? 0).toFixed(2)}%/{risk.policy.max_open_risk_pct}%</span></div>
        {risk.usage.cooldown_remaining_minutes > 0 && <span className="risk-cooldown">Cooldown {risk.usage.cooldown_remaining_minutes}m</span>}
        {risk.events.slice(0, 2).map((event, i) => <span key={`${event.ts}:${i}`} className={`risk-event ${event.disposition}`}>{event.disposition === 'blocked' ? '⛔' : '⚠'} {event.detail}</span>)}
      </div>}
      {account?.positions.map((p) => (
        <div key={p.symbol} className={`pos-row ${p.unrealized >= 0 ? 'up' : 'down'}`}>
          <strong>
            {p.qty > 0 ? 'LONG' : 'SHORT'} {Math.abs(p.qty)} {p.symbol}
          </strong>
          <span>@ {p.avg_price.toFixed(2)}</span>
          <span className="pnl">
            {p.unrealized >= 0 ? '+' : ''}
            {p.unrealized.toFixed(2)}
          </span>
        </div>
      ))}
      {account?.working_orders
        .filter((o) => o.status === 'working' || o.status === 'pending')
        .map((o) => (
          <div key={o.id} className="order-row">
            <span className="muted">
              {o.role} {o.side} {o.qty} {o.type}
              {o.limit_price != null ? ` @${o.limit_price.toFixed(2)}` : ''}
              {o.stop_price != null ? ` stop ${o.stop_price.toFixed(2)}` : ''}
            </span>
            <button onClick={() => void cancel(o.id)} title="Cancel">
              ✕
            </button>
          </div>
        ))}
      {events.length > 0 && (
        <div className="fills-feed">
          {events
            .slice(-8)
            .reverse()
            .map((e, i) => (
              <div key={i} className={`feed-row ${e.kind}`}>
                <span className="feed-kind">{e.kind.replace('_', ' ')}</span> {e.detail}
              </div>
            ))}
        </div>
      )}
    </div>
  )
}
