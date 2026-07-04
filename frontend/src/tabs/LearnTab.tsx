import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { LessonListItem } from '../lib/types'
import { LessonTakeover } from '../lesson/LessonTakeover'

const STATUS_LABEL: Record<LessonListItem['status'], string> = {
  available: 'Start',
  complete: '✓ Complete',
  locked: '🔒 Locked',
  unavailable: '⚠ Unavailable',
}

export function LearnTab() {
  const lessonsQ = useQuery({ queryKey: ['lessons'], queryFn: api.lessons })
  const [active, setActive] = useState<number | null>(null)

  if (active != null) {
    return <LessonTakeover moduleNumber={active} onExit={() => setActive(null)} />
  }

  const modules = lessonsQ.data?.modules ?? []
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
        {[8, 9, 10].map((n) => (
          <div key={n} className="module-row">
            <span className="num">{n}</span>
            <span className="module-info">
              <span className="module-title">
                {n === 8 ? 'Core setups' : n === 9 ? 'Risk management' : 'Trade planning, journaling, psychology'}
              </span>
              <span className="module-summary">Arrives with the rules engine build phase.</span>
            </span>
            <span className="module-meta">
              <span className="lock">🔒 Locked</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
