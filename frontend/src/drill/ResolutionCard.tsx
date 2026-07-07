import type { DrillResolution, GradeInfo } from '../lib/types'

function fmtR(v: number | null): string {
  if (v == null) return '—'
  return `${v > 0 ? '+' : ''}${v}R`
}

function GradeBlock({ title, grade }: { title: string; grade: GradeInfo }) {
  return (
    <div className={`grade-card ${grade.tier.toLowerCase()}`}>
      <div className="grade-tier">
        {title}: {grade.tier}
      </div>
      {grade.note && <div className="grade-note">{grade.note}</div>}
      <ul className="grade-checklist">
        {grade.checklist.map((c) => (
          <li key={c.key} className={c.passed ? 'pass' : 'fail'} title={c.detail}>
            {c.passed ? '✓' : '✗'} {c.label}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** The reveal: what fired, how the coach graded it, what it actually did,
 * and what YOU did about it. */
export function ResolutionCard({ r }: { r: DrillResolution }) {
  const { setup, outcome, user } = r
  const outcomeLabel =
    outcome.outcome === 'never_triggered' ? 'never triggered' : outcome.outcome
  return (
    <div className="resolution-card">
      <h4>
        {setup.setup_type} ({setup.direction}) fired at {setup.fired_et} ET
      </h4>
      <div className="resolution-bracket">
        entry {setup.entry ?? '—'} · stop {setup.stop ?? '—'} · target {setup.target ?? '—'}
        {setup.rr != null && <> · R:R {setup.rr}</>}
      </div>
      {setup.coach_grade && <GradeBlock title="Coach" grade={setup.coach_grade} />}
      <div className={`resolution-outcome ${outcome.r_multiple != null && outcome.r_multiple > 0 ? 'up' : 'down'}`}>
        Natural outcome: <strong>{outcomeLabel}</strong>
        {outcome.r_multiple != null && <> ({fmtR(outcome.r_multiple)})</>}
      </div>
      <div className="resolution-you">
        {user.took ? (
          <>
            You traded it{user.grade && <> — graded at entry</>}.
            {user.trade && (
              <div className="resolution-trade">
                fill {user.trade.entry_price.toFixed(2)} →{' '}
                {user.trade.exit_price != null ? user.trade.exit_price.toFixed(2) : 'open'} (
                {user.trade.exit_reason ?? 'open'}) {fmtR(user.trade.r_multiple)}
              </div>
            )}
          </>
        ) : (
          <>You passed.</>
        )}
      </div>
      {user.grade && <GradeBlock title="Your entry" grade={user.grade} />}
    </div>
  )
}
