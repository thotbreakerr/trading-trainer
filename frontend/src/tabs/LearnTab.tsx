import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { DrillSetupInfo, LessonListItem } from '../lib/types'
import { DrillTakeover } from '../drill/DrillTakeover'
import { LessonTakeover } from '../lesson/LessonTakeover'

const STATUS_LABEL: Record<LessonListItem['status'], string> = {
  available: 'Start',
  complete: '✓ Complete',
  locked: '🔒 Locked',
  unavailable: '⚠ Unavailable',
}

const TIERS = ['Textbook', 'Solid', 'Risky', 'Reckless'] as const

function DrillCard({
  s,
  count,
  onStart,
}: {
  s: DrillSetupInfo
  count: number
  onStart: () => void
}) {
  return (
    <div className="drill-card">
      <div className="drill-card-head">
        <strong>{s.label}</strong>
        <button className="btn-primary" onClick={onStart}>
          Drill {count}
        </button>
      </div>
      <div className="drill-card-stats muted">
        {s.attempts === 0 ? (
          'No reps yet'
        ) : (
          <>
            {s.attempts} rep{s.attempts === 1 ? '' : 's'} · {s.taken} taken / {s.passed} passed
            {TIERS.filter((t) => s.grade_distribution[t]).map((t) => (
              <span key={t} className={`drill-chip ${t.toLowerCase()}`}>
                {t} ×{s.grade_distribution[t]}
              </span>
            ))}
            {s.taken_avg_outcome_r != null && <> · taken avg {s.taken_avg_outcome_r}R</>}
            {s.passed_avg_outcome_r != null && <> · passed avg {s.passed_avg_outcome_r}R</>}
          </>
        )}
      </div>
    </div>
  )
}

export function LearnTab() {
  const lessonsQ = useQuery({ queryKey: ['lessons'], queryFn: api.lessons })
  const drillQ = useQuery({ queryKey: ['drillSetups'], queryFn: api.drillSetups })
  const [active, setActive] = useState<number | null>(null)
  const [drill, setDrill] = useState<{ key: string; label: string } | null>(null)
  const [count, setCount] = useState(5)

  if (active != null) {
    return <LessonTakeover moduleNumber={active} onExit={() => setActive(null)} />
  }
  if (drill != null) {
    return (
      <DrillTakeover
        setupKey={drill.key}
        label={drill.label}
        count={count}
        onExit={() => setDrill(null)}
      />
    )
  }

  const modules = lessonsQ.data?.modules ?? []
  const drillInfo = drillQ.data
  return (
    <div className="stub learn">
      <h2>Learn</h2>
      <p style={{ color: 'var(--muted)' }}>
        Ten modules, unlocked in order, every one taught on real historical market days.
      </p>
      {lessonsQ.isError && <p className="banner">⚠ {String(lessonsQ.error)}</p>}
      <div className="module-list">
        {modules.map((m) => {
          const clickable = m.status === 'available' || m.status === 'complete'
          return (
            <button
              key={m.module}
              className={`module-row ${m.status} ${clickable ? 'clickable' : ''}`}
              disabled={!clickable}
              title={m.status === 'unavailable' ? (m.status_reason ?? '') : ''}
              onClick={() => clickable && setActive(m.module)}
            >
              <span className="num">{m.module}</span>
              <span className="module-info">
                <span className="module-title">{m.title}</span>
                {m.summary && <span className="module-summary">{m.summary}</span>}
              </span>
              <span className="module-meta">
                {m.total_steps > 0 && m.status !== 'locked' && (
                  <span className="module-steps">
                    {m.completed_steps}/{m.total_steps}
                  </span>
                )}
                <span className="lock">{STATUS_LABEL[m.status]}</span>
              </span>
            </button>
          )
        })}
      </div>

      <h2 className="drill-heading">Drill a setup</h2>
      {drillInfo && !drillInfo.unlocked && (
        <p style={{ color: 'var(--muted)' }}>
          🔒 Unlocks with Module {drillInfo.gate_module} — Core setups. Then: unlimited reps of
          any setup, mined from real cached days, graded like practice.
        </p>
      )}
      {drillInfo?.unlocked && (
        <>
          <p style={{ color: 'var(--muted)' }}>
            Reps build the skill: replay a real instance blind, trade it or pass, see what it
            did. Instances per run:{' '}
            {[3, 5, 10].map((n) => (
              <button
                key={n}
                className={`drill-count ${count === n ? 'active' : ''}`}
                onClick={() => setCount(n)}
              >
                {n}
              </button>
            ))}
          </p>
          <div className="drill-cards">
            {drillInfo.setups.map((s) => (
              <DrillCard
                key={s.key}
                s={s}
                count={count}
                onStart={() => setDrill({ key: s.key, label: s.label })}
              />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
