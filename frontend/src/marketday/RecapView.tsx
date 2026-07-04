import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { RecapLedgerItem, RecapTrade } from '../lib/types'

function r(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${v > 0 ? '+' : ''}${v}R`
}

export function RecapView({
  onReview,
}: {
  onReview: (symbol: string, day: string, startAt: number) => void
}) {
  const recapQ = useQuery({ queryKey: ['recap'], queryFn: () => api.recap() })
  if (recapQ.isPending) return <div className="boot">Building the recap…</div>
  if (recapQ.isError) return <div className="boot error">⚠ {String(recapQ.error)}</div>
  const recap = recapQ.data!
  const traj = recap.trajectory

  return (
    <div className="recap">
      <div className="view-head">
        <h2>EOD recap — {recap.day}</h2>
        {recap.ledger_computed_on_demand && (
          <span className="muted">ledger computed on demand (app wasn't watching)</span>
        )}
      </div>

      <h3>Setup ledger</h3>
      {recap.ledger.length === 0 ? (
        <p className="muted">Nothing fired on the watchlist today.</p>
      ) : (
        <table className="recap-table">
          <thead>
            <tr>
              <th>fired</th><th>symbol</th><th>setup</th><th>dir</th><th>grade</th>
              <th>took?</th><th>outcome</th>
            </tr>
          </thead>
          <tbody>
            {recap.ledger.map((item: RecapLedgerItem, i) => (
              <tr key={i} className={item.taken ? 'taken' : ''}>
                <td>{item.fired_et}</td>
                <td>{item.symbol}</td>
                <td>{item.setup_type.replace(/_/g, ' ')}</td>
                <td>{item.direction}</td>
                <td>
                  <span className={`grade-chip ${(item.grade ?? '').toLowerCase()}`}>
                    {item.grade ?? '—'}
                  </span>
                </td>
                <td>{item.taken ? `yes (${item.user_grade ?? '—'})` : 'passed'}</td>
                <td>
                  {item.outcome ?? '—'} {item.outcome_r != null && r(item.outcome_r)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3>Your trades</h3>
      {recap.trades.length === 0 ? (
        <p className="muted">No trades today.</p>
      ) : (
        <table className="recap-table">
          <thead>
            <tr>
              <th>entry</th><th>symbol</th><th>dir</th><th>qty</th><th>exit</th>
              <th>R</th><th></th>
            </tr>
          </thead>
          <tbody>
            {recap.trades.map((t: RecapTrade, i) => (
              <tr key={i}>
                <td>{t.entry_et} @ {t.entry_price.toFixed(2)}</td>
                <td>{t.symbol}</td>
                <td>{t.direction}</td>
                <td>{t.qty}</td>
                <td>{t.exit_price?.toFixed(2) ?? '—'} ({t.exit_reason ?? '—'})</td>
                <td className={t.r_multiple != null && t.r_multiple > 0 ? 'chg up' : 'chg down'}>
                  {r(t.r_multiple)}
                </td>
                <td>
                  <button
                    className="btn-replay"
                    onClick={() => onReview(t.review.symbol, t.review.day, t.review.start_at)}
                  >
                    ▶ Review
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="brief-columns">
        <div>
          <h3>Plan vs. reality</h3>
          {!recap.plan_vs_reality.taken ? (
            <p className="muted">No briefing taken this morning.</p>
          ) : (
            <>
              <p className="muted">
                Morning focus: {recap.plan_vs_reality.focus_was?.join(', ') || '—'}
              </p>
              <table className="recap-table">
                <thead>
                  <tr>
                    <th>symbol</th><th>planned gap</th><th>day chg</th><th>range</th><th>levels broken</th>
                  </tr>
                </thead>
                <tbody>
                  {(recap.plan_vs_reality.reality ?? []).map((row, i) => (
                    <tr key={i}>
                      <td>{row.symbol}</td>
                      <td>{row.planned_gap_pct != null ? `${row.planned_gap_pct}%` : '—'}</td>
                      <td>{row.day_change_pct != null ? `${row.day_change_pct}%` : '—'}</td>
                      <td>{row.range_pct != null ? `${row.range_pct}%` : '—'}</td>
                      <td>
                        {[row.broke_pdh && 'PDH', row.broke_pdl && 'PDL']
                          .filter(Boolean)
                          .join(', ') || 'none'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
        <div>
          <h3>Trajectory</h3>
          <div className="stat-cards">
            <div className="stat-card">
              <span className="muted">win rate</span>
              <strong>
                {traj.cumulative.win_rate != null
                  ? `${Math.round((traj.cumulative.win_rate as number) * 100)}%`
                  : '—'}
              </strong>
            </div>
            <div className="stat-card">
              <span className="muted">expectancy</span>
              <strong>{r(traj.cumulative.expectancy_r as number | null)}</strong>
            </div>
            <div className="stat-card">
              <span className="muted">total</span>
              <strong>{r(traj.cumulative.total_r as number | null)}</strong>
            </div>
            <div className="stat-card">
              <span className="muted">trades</span>
              <strong>{traj.cumulative.trades ?? 0}</strong>
            </div>
          </div>
          <p className="muted">
            Grades:{' '}
            {Object.entries(traj.grade_distribution)
              .map(([g, n]) => `${g} ×${n}`)
              .join(' · ') || 'no graded trades yet'}
          </p>
        </div>
      </div>
    </div>
  )
}
