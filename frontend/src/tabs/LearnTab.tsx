import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { handleAppLink, type LearnSection } from '../lib/routing'
import type { DrillSetupInfo, LessonListItem, WorkoutItem } from '../lib/types'
import { DrillTakeover } from '../drill/DrillTakeover'
import { LessonTakeover } from '../lesson/LessonTakeover'
import { ScenarioExplorer } from '../scenario/ScenarioExplorer'
import { ScenarioTakeover } from '../scenario/ScenarioTakeover'
import { DailyWorkoutCard } from '../workout/DailyWorkout'
import { EmptyState, ErrorState, LoadingState } from '../shell/AsyncState'

const STATUS_LABEL: Record<LessonListItem['status'], string> = {
  available: 'Start',
  complete: 'Review',
  locked: 'Locked',
  unavailable: 'Unavailable',
}

const SECTIONS: { id: LearnSection; label: string; detail: string }[] = [
  { id: 'today', label: 'Today', detail: 'Your next best work' },
  { id: 'curriculum', label: 'Curriculum', detail: 'Structured lessons' },
  { id: 'drills', label: 'Drills', detail: 'Repeat a setup' },
  { id: 'scenarios', label: 'Scenarios', detail: 'Explore history' },
]

const TIERS = ['Textbook', 'Solid', 'Risky', 'Reckless'] as const

function ProgressBar({ value, max, label }: { value: number; max: number; label: string }) {
  const pct = max ? Math.round((value / max) * 100) : 0
  return (
    <div className="module-progress" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={value}>
      <span style={{ width: `${pct}%` }} />
    </div>
  )
}

function ModuleRow({ module, onOpen }: { module: LessonListItem; onOpen: () => void }) {
  const clickable = module.status === 'available' || module.status === 'complete'
  return (
    <button
      className={`module-row ${module.status} ${clickable ? 'clickable' : ''}`}
      disabled={!clickable}
      title={module.status === 'unavailable' ? (module.status_reason ?? '') : ''}
      onClick={onOpen}
    >
      <span className="num">{module.status === 'complete' ? '✓' : module.module}</span>
      <span className="module-info">
        <span className="module-title">{module.title}</span>
        {module.summary && <span className="module-summary">{module.summary}</span>}
        {module.total_steps > 0 && module.status !== 'locked' && (
          <ProgressBar value={module.completed_steps} max={module.total_steps} label={`${module.title} progress`} />
        )}
      </span>
      <span className="module-meta">
        {module.total_steps > 0 && module.status !== 'locked' && <span className="module-steps">{module.completed_steps}/{module.total_steps}</span>}
        <span className="lock">{STATUS_LABEL[module.status]}</span>
      </span>
    </button>
  )
}

function ContinueCard({ module, onOpen }: { module: LessonListItem; onOpen: () => void }) {
  const started = module.completed_steps > 0
  return (
    <section className="continue-card">
      <span className="eyebrow">{started ? 'Continue where you left off' : 'Recommended next lesson'}</span>
      <div className="continue-content">
        <span className="continue-number">{module.module}</span>
        <div>
          <h2>{module.title}</h2>
          <p>{module.summary}</p>
          <ProgressBar value={module.completed_steps} max={module.total_steps} label={`${module.title} progress`} />
          <span className="muted">{module.completed_steps}/{module.total_steps} steps complete</span>
        </div>
        <button className="btn-primary" onClick={onOpen}>{started ? 'Resume lesson' : 'Start lesson'}</button>
      </div>
    </section>
  )
}

function DrillCard({ s, count, onStart }: { s: DrillSetupInfo; count: number; onStart: () => void }) {
  return (
    <div className="drill-card">
      <div className="drill-card-head">
        <strong>{s.label}</strong>
        <button className="btn-primary" onClick={onStart}>Drill {count}</button>
      </div>
      <div className="drill-card-stats muted">
        {s.attempts === 0 ? 'No reps yet' : (
          <>
            {s.attempts} rep{s.attempts === 1 ? '' : 's'} · {s.taken} taken / {s.passed} passed
            {TIERS.filter((tier) => s.grade_distribution[tier]).map((tier) => (
              <span key={tier} className={`drill-chip ${tier.toLowerCase()}`}>{tier} ×{s.grade_distribution[tier]}</span>
            ))}
            {s.taken_avg_outcome_r != null && <> · taken avg {s.taken_avg_outcome_r}R</>}
            {s.passed_avg_outcome_r != null && <> · passed avg {s.passed_avg_outcome_r}R</>}
          </>
        )}
      </div>
    </div>
  )
}

export function LearnTab({
  section,
  moduleNumber,
  onNavigate,
}: {
  section: LearnSection
  moduleNumber: number | null
  onNavigate: (to: string) => void
}) {
  const queryClient = useQueryClient()
  const lessonsQ = useQuery({ queryKey: ['lessons'], queryFn: api.lessons })
  const drillQ = useQuery({ queryKey: ['drillSetups'], queryFn: api.drillSetups })
  const [drill, setDrill] = useState<{ key: string; label: string; count?: number; workout?: { runId: number; itemId: number } } | null>(null)
  const [count, setCount] = useState(5)
  const [scenarioId, setScenarioId] = useState<string | null>(null)
  const [showLocked, setShowLocked] = useState(false)

  if (moduleNumber != null) {
    return <LessonTakeover moduleNumber={moduleNumber} onExit={() => onNavigate('/learn/curriculum')} />
  }
  if (drill != null) {
    return (
      <DrillTakeover
        setupKey={drill.key}
        label={drill.label}
        count={drill.count ?? count}
        onExit={() => setDrill(null)}
        onComplete={drill.workout ? () => void api.completeWorkoutItem(drill.workout!.runId, drill.workout!.itemId).then(() => queryClient.invalidateQueries({ queryKey: ['dailyWorkout'] })) : undefined}
      />
    )
  }
  if (scenarioId != null) return <ScenarioTakeover id={scenarioId} onExit={() => setScenarioId(null)} />

  const modules = lessonsQ.data?.modules ?? []
  const continueModule = modules.find((item) => item.status === 'available' && item.completed_steps > 0)
    ?? modules.find((item) => item.status === 'available')
  const visibleModules = modules.filter((item) => item.status !== 'locked')
  const lockedModules = modules.filter((item) => item.status === 'locked')
  const completedModules = modules.filter((item) => item.status === 'complete').length
  const completedSteps = modules.reduce((total, item) => total + item.completed_steps, 0)
  const totalSteps = modules.reduce((total, item) => total + item.total_steps, 0)

  const openModule = (module: number) => onNavigate(`/learn/module/${module}`)
  const nav = (
    <nav className="learn-nav" aria-label="Learning sections">
      {SECTIONS.map((item) => (
        <a
          key={item.id}
          href={`/learn/${item.id}`}
          className={section === item.id ? 'active' : ''}
          aria-current={section === item.id ? 'page' : undefined}
          onClick={(event) => handleAppLink(event, `/learn/${item.id}`)}
        >
          <strong>{item.label}</strong><small>{item.detail}</small>
        </a>
      ))}
    </nav>
  )

  return (
    <div className="stub learn">
      <header className="learn-head">
        <div><span className="eyebrow">Build skill deliberately</span><h1>Learn</h1></div>
        {totalSteps > 0 && <span className="overall-progress">{completedModules}/{modules.length} modules · {completedSteps}/{totalSteps} steps</span>}
      </header>
      {nav}

      {lessonsQ.isPending && <LoadingState label="Loading your learning plan" />}
      {lessonsQ.isError && <ErrorState title="Could not load the curriculum" error={lessonsQ.error} onRetry={() => void lessonsQ.refetch()} />}

      {!lessonsQ.isPending && !lessonsQ.isError && section === 'today' && (
        <div className="learn-section">
          <div className="section-intro"><div><span className="eyebrow">Today</span><h2>Your next best work</h2><p>Resume one lesson or complete the practice blocks selected from your recent decisions.</p></div></div>
          {continueModule ? <ContinueCard module={continueModule} onOpen={() => openModule(continueModule.module)} /> : (
            <EmptyState title="Curriculum complete" body="Review a lesson or sharpen a setup with a focused drill." action={<button className="btn-replay" onClick={() => onNavigate('/learn/drills')}>Choose a drill</button>} />
          )}
          <DailyWorkoutCard onStart={(item: WorkoutItem, runId: number) => setDrill({ key: item.setup, label: item.label, count: item.reps, workout: { runId, itemId: item.id } })} />
        </div>
      )}

      {!lessonsQ.isPending && !lessonsQ.isError && section === 'curriculum' && (
        <div className="learn-grid">
          <section className="learn-section">
            <div className="section-intro"><div><span className="eyebrow">Curriculum</span><h2>Build the foundation in order</h2><p>Every module uses real historical market days and keeps your place.</p></div></div>
            {continueModule && <ContinueCard module={continueModule} onOpen={() => openModule(continueModule.module)} />}
            <div className="module-list">
              {visibleModules.map((item) => <ModuleRow key={item.module} module={item} onOpen={() => openModule(item.module)} />)}
            </div>
            {lockedModules.length > 0 && (
              <section className="locked-roadmap">
                <button className="locked-toggle" aria-expanded={showLocked} onClick={() => setShowLocked((value) => !value)}>
                  <span><strong>Upcoming roadmap</strong><small>{lockedModules.length} modules unlock in order</small></span>
                  <span aria-hidden="true">{showLocked ? '−' : '+'}</span>
                </button>
                {showLocked && <div className="module-list">{lockedModules.map((item) => <ModuleRow key={item.module} module={item} onOpen={() => undefined} />)}</div>}
              </section>
            )}
          </section>
          <aside className="progress-sidebar">
            <span className="eyebrow">Your progress</span>
            <strong className="progress-big">{totalSteps ? Math.round((completedSteps / totalSteps) * 100) : 0}%</strong>
            <ProgressBar value={completedSteps} max={totalSteps} label="Overall curriculum progress" />
            <span className="muted">{completedSteps} of {totalSteps} lesson steps</span>
            <hr />
            <span><strong>{completedModules}</strong> modules complete</span>
            <span><strong>{modules.length - completedModules}</strong> modules remaining</span>
          </aside>
        </div>
      )}

      {section === 'drills' && (
        <section className="learn-section drills-section">
          <div className="section-intro"><div><span className="eyebrow">Drills</span><h2>Repeat one setup until the read is automatic</h2><p>Practice blind on real cached instances, then compare your decision with the outcome.</p></div></div>
          {drillQ.isPending && <LoadingState label="Loading drill history" />}
          {drillQ.isError && <ErrorState title="Could not load drills" error={drillQ.error} onRetry={() => void drillQ.refetch()} />}
          {drillQ.data && !drillQ.data.unlocked && <EmptyState title="Drills are still locked" body={`Complete Module ${drillQ.data.gate_module} — Core setups — to unlock unlimited practice.`} action={<button className="btn-replay" onClick={() => onNavigate('/learn/curriculum')}>View curriculum</button>} />}
          {drillQ.data?.unlocked && (
            <>
              <fieldset className="rep-picker"><legend>Instances per run</legend>{[3, 5, 10].map((value) => <button key={value} className={`drill-count ${count === value ? 'active' : ''}`} aria-pressed={count === value} onClick={() => setCount(value)}>{value}</button>)}</fieldset>
              <div className="drill-cards">{drillQ.data.setups.map((setup) => <DrillCard key={setup.key} s={setup} count={count} onStart={() => setDrill({ key: setup.key, label: setup.label })} />)}</div>
            </>
          )}
        </section>
      )}

      {section === 'scenarios' && <ScenarioExplorer onStart={(scenario) => setScenarioId(scenario.id)} />}
    </div>
  )
}
