import type { TrajectoryData } from '../lib/types'

const GRADE_COLORS: Record<string, string> = {
  Textbook: '#26a69a',
  Solid: '#2962ff',
  Risky: '#ff9800',
  Reckless: '#ef5350',
  ungraded: '#787b86',
}
const GRADE_ORDER = ['Textbook', 'Solid', 'Risky', 'Reckless', 'ungraded']

/** The headline metric (doc §11.4): grade distribution over time as stacked
 * bars — process quality leading, P&L lagging. Hand-rolled SVG, no deps. */
export function GradeDistributionChart({ data }: { data: TrajectoryData }) {
  const days = data.grade_by_day
  if (!days.length) return <p className="muted">No graded trades yet — they start in Module 8.</p>
  const w = 640
  const h = 160
  const gap = 4
  const barW = Math.max(6, Math.min(36, (w - 40) / days.length - gap))
  const maxCount = Math.max(...days.map((d) => Object.values(d.grades).reduce((a, b) => a + b, 0)))
  return (
    <svg viewBox={`0 0 ${w} ${h + 30}`} className="traj-chart" role="img" aria-label="Grade distribution by day">
      {days.map((d, i) => {
        const x = 30 + i * (barW + gap)
        let y = h
        return (
          <g key={d.day}>
            {GRADE_ORDER.filter((g) => d.grades[g]).map((g) => {
              const value = d.grades[g]
              const barH = (value / maxCount) * (h - 10)
              y -= barH
              return (
                <rect key={g} x={x} y={y} width={barW} height={barH} fill={GRADE_COLORS[g]}>
                  <title>{`${d.day}: ${g} ×${value}`}</title>
                </rect>
              )
            })}
            {(days.length <= 14 || i % Math.ceil(days.length / 10) === 0) && (
              <text x={x + barW / 2} y={h + 16} className="traj-label" textAnchor="middle">
                {d.day.slice(5)}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}

export function EquityCurve({ data }: { data: TrajectoryData }) {
  const points = data.equity_curve_r
  if (points.length < 2) return <p className="muted">The equity curve draws after a few closed trades.</p>
  const w = 640
  const h = 140
  const values = points.map((p) => p.cum_r)
  const lo = Math.min(0, ...values)
  const hi = Math.max(0, ...values)
  const span = hi - lo || 1
  const x = (i: number) => 6 + (i / (points.length - 1)) * (w - 12)
  const y = (v: number) => 8 + (1 - (v - lo) / span) * (h - 16)
  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.cum_r).toFixed(1)}`).join(' ')
  const zero = y(0)
  const last = values[values.length - 1]
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="traj-chart" role="img" aria-label="Cumulative R equity curve">
      <line x1={0} x2={w} y1={zero} y2={zero} className="traj-zero" />
      <path d={path} fill="none" stroke={last >= 0 ? '#26a69a' : '#ef5350'} strokeWidth={2} />
      <text x={w - 6} y={y(last) - 6} textAnchor="end" className="traj-label">
        {last >= 0 ? '+' : ''}
        {last}R
      </text>
    </svg>
  )
}
