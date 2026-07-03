// Static curriculum preview (doc §6) — the lesson engine turns these live.
const MODULES = [
  'Reading the chart',
  'Order types',
  'Key levels',
  'Trend & structure',
  'VWAP',
  'Volume analysis',
  'The open',
  'Core setups',
  'Risk management',
  'Trade planning, journaling, psychology',
]

export function LearnTab() {
  return (
    <div className="stub">
      <h2>Learn</h2>
      <p style={{ color: 'var(--muted)' }}>
        Ten modules, unlocked in order, each taught on real historical days. The lesson
        player arrives in the next build phase.
      </p>
      <div className="module-list">
        {MODULES.map((title, i) => (
          <div key={title} className="module-row">
            <span className="num">{i + 1}</span>
            <span>{title}</span>
            <span className="lock">🔒 coming soon</span>
          </div>
        ))}
      </div>
    </div>
  )
}
