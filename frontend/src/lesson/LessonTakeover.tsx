import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { LessonStepData, Timeframe } from '../lib/types'
import { ChartErrorBoundary } from '../chart/ChartErrorBoundary'
import { ChartPane } from '../chart/ChartPane'
import { TimeframeSwitcher } from '../chart/TimeframeSwitcher'
import { useBars } from '../chart/useBars'
import { OrderTicket } from '../sim/OrderTicket'
import { PositionPanel } from '../sim/PositionPanel'
import { GuidedPointer } from './GuidedPointer'
import { Markdown } from './Markdown'
import { useLessonReplay } from './useLessonReplay'

const ct = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/Chicago',
  hour: 'numeric',
  minute: '2-digit',
})
const et = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  hour: 'numeric',
  minute: '2-digit',
})

function shuffled(n: number): number[] {
  const order = [...Array(n).keys()]
  for (let i = order.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[order[i], order[j]] = [order[j], order[i]]
  }
  return order
}

function QuizStep({
  moduleNumber,
  step,
  onCompleted,
}: {
  moduleNumber: number
  step: LessonStepData
  onCompleted: () => void
}) {
  const choices = step.choices ?? []
  const [order, setOrder] = useState(() => shuffled(choices.length))
  const [selected, setSelected] = useState<number | null>(null)
  const [result, setResult] = useState<{ correct: boolean; explain: string } | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setOrder(shuffled(choices.length))
    setSelected(null)
    setResult(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step.index])

  const submit = async () => {
    if (selected == null) return
    setBusy(true)
    try {
      const r = await api.completeStep(moduleNumber, step.index, { answer: selected })
      setResult({ correct: r.correct ?? false, explain: r.explain ?? '' })
      if (r.correct) onCompleted()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="quiz">
      <Markdown text={step.question ?? ''} />
      <div className="quiz-choices">
        {order.map((orig) => (
          <label key={orig} className={selected === orig ? 'selected' : ''}>
            <input
              type="radio"
              name={`quiz-${step.index}`}
              checked={selected === orig}
              onChange={() => {
                setSelected(orig)
                setResult(null)
              }}
            />
            {choices[orig]}
          </label>
        ))}
      </div>
      {result && (
        <div className={`quiz-result ${result.correct ? 'right' : 'wrong'}`}>
          <strong>{result.correct ? 'Correct.' : 'Not quite.'}</strong>
          <Markdown text={result.explain} />
          {!result.correct && <p className="retry-note">Pick another answer and try again.</p>}
        </div>
      )}
      {!result?.correct && (
        <button className="btn-primary" disabled={selected == null || busy} onClick={() => void submit()}>
          Check answer
        </button>
      )}
    </div>
  )
}

export function LessonTakeover({
  moduleNumber,
  onExit,
}: {
  moduleNumber: number
  onExit: () => void
}) {
  const queryClient = useQueryClient()
  const lessonQ = useQuery({
    queryKey: ['lesson', moduleNumber],
    queryFn: () => api.lesson(moduleNumber),
  })
  const [stepIndex, setStepIndex] = useState<number | null>(null)
  const [tf, setTf] = useState<Timeframe>('5m')
  const [stepDone, setStepDone] = useState(false)

  const lesson = lessonQ.data
  const steps = lesson?.steps ?? []
  useEffect(() => {
    if (lesson && stepIndex === null) {
      const firstIncomplete = lesson.steps.find((s) => !s.completed)
      setStepIndex(firstIncomplete ? firstIncomplete.index : 0)
    }
  }, [lesson, stepIndex])

  const step: LessonStepData | null = stepIndex != null ? (steps[stepIndex] ?? null) : null
  useEffect(() => setStepDone(step?.completed ?? false), [step?.index, step?.completed])

  const replay = useLessonReplay(moduleNumber, step?.type === 'replay' || step?.type === 'practice' ? step : null)

  // Chart source: the step's own session, else the module's default chart day.
  const chartSymbol = step?.symbol ?? lesson?.chart?.symbol ?? null
  const chartDay = step?.date ?? lesson?.chart?.date ?? null
  const browseQ = useBars(chartSymbol ?? 'SPY', replay.session ? null : chartDay, tf)
  const sessionQ = useQuery({
    queryKey: ['sessionBars', replay.session?.id ?? 'none', tf],
    queryFn: () => api.sessionBars(replay.session!.id, tf),
    enabled: !!replay.session,
    staleTime: 0,
  })
  const practiceAccountQ = useQuery({
    queryKey: ['account', replay.session?.id ?? 'none', replay.stepCount],
    queryFn: () => api.account(replay.session!.id),
    enabled: !!replay.session && step?.type === 'practice',
    staleTime: 0,
  })
  const chartData = replay.session ? sessionQ.data : browseQ.data

  const markComplete = async () => {
    if (!step || stepDone) return
    await api.completeStep(moduleNumber, step.index)
    setStepDone(true)
    await queryClient.invalidateQueries({ queryKey: ['lesson', moduleNumber] })
  }

  const next = async () => {
    if (stepIndex == null) return
    if (stepIndex + 1 < steps.length) {
      setStepIndex(stepIndex + 1)
    } else {
      await queryClient.invalidateQueries({ queryKey: ['lessons'] })
      onExit()
    }
  }

  if (lessonQ.isPending || !lesson || step == null) {
    return <div className="boot">Loading lesson…</div>
  }

  const clockLabel =
    replay.clock != null
      ? `${ct.format(new Date(replay.clock * 1000))} CT (${et.format(new Date(replay.clock * 1000))} ET)`
      : null
  const currentPause = replay.atPause ? replay.pauses[replay.pauseIndex] : null
  const canAdvance =
    stepDone ||
    (step.type === 'explain' && true) ||
    (step.type === 'replay' && replay.scriptFinished)

  return (
    <div className="lesson-takeover">
      <header className="lesson-header">
        <button className="lesson-back" onClick={onExit}>
          ← Modules
        </button>
        <span className="lesson-title">
          Module {lesson.module}: {lesson.title}
        </span>
        <span className="lesson-progress">
          {steps.map((s) => (
            <span
              key={s.index}
              className={`dot ${s.completed ? 'done' : ''} ${s.index === step.index ? 'here' : ''}`}
            />
          ))}
        </span>
      </header>

      <div className="lesson-chart">
        <div className="lesson-chart-bar">
          <span className="symbol">{chartSymbol ?? '—'}</span>
          {chartDay && <span className="lesson-day">{chartDay}</span>}
          {clockLabel && <span className="replay-clock">{clockLabel}</span>}
          {replay.session && step.type === 'replay' && (
            <span className="lesson-replay-controls">
              <button
                data-pointer-id="replay-play"
                onClick={replay.playToNextPause}
                disabled={replay.running || replay.atPause || replay.done}
              >
                {replay.pauseIndex < replay.pauses.length ? '▶ to next pause' : '▶ to close'}
              </button>
              <button data-pointer-id="replay-step" onClick={replay.stepOne} disabled={replay.running}>
                +1
              </button>
              <button data-pointer-id="replay-restart" onClick={replay.restart}>
                ↺
              </button>
            </span>
          )}
          {replay.session && step.type === 'practice' && (
            <span className="lesson-replay-controls">
              <button data-pointer-id="replay-play" onClick={replay.playPause}>
                {replay.playing ? '⏸' : '▶'}
              </button>
              <button data-pointer-id="replay-step" onClick={replay.stepOne} disabled={replay.playing}>
                +1
              </button>
              {[1, 2, 5].map((s) => (
                <button
                  key={s}
                  className={replay.speed === s ? 'active' : ''}
                  onClick={() => replay.setSpeed(s as 1 | 2 | 5)}
                >
                  {s}×
                </button>
              ))}
              <button data-pointer-id="replay-restart" onClick={replay.restart}>
                ↺
              </button>
            </span>
          )}
          <TimeframeSwitcher tf={tf} onChange={setTf} />
        </div>
        <ChartErrorBoundary>
          <ChartPane
            bars={chartData?.bars ?? []}
            days={chartData?.days ?? []}
            overlays={chartData?.overlays}
            follow={replay.running || replay.playing}
            fitKey={`${chartSymbol}:${chartDay}:${replay.session?.id ?? 'browse'}`}
          />
        </ChartErrorBoundary>
      </div>

      <div className="lesson-panel">
        <h3>{step.title}</h3>
        <Markdown text={step.body} />

        {step.type === 'quiz' && (
          <QuizStep moduleNumber={moduleNumber} step={step} onCompleted={() => setStepDone(true)} />
        )}

        {step.type === 'replay' && currentPause && (
          <div className="pause-note">
            <div className="pause-time">Paused at {currentPause.at} ET</div>
            <Markdown text={currentPause.note} />
            <button className="btn-primary" onClick={replay.continueFromPause}>
              Continue
            </button>
          </div>
        )}

        {step.type === 'practice' && step.goal && (
          <div className="practice-layout">
            <div className="practice-goal">
              <h4>Your goal</h4>
              <Markdown text={step.goal} />
              {!stepDone && (
                <button className="btn-primary" onClick={() => void markComplete()}>
                  Mark practice complete
                </button>
              )}
            </div>
            {replay.session && (
              <div className="practice-sim">
                <OrderTicket
                  sessionId={replay.session.id}
                  lastPrice={
                    sessionQ.data?.bars[sessionQ.data.bars.length - 1]?.c ?? null
                  }
                  equity={practiceAccountQ.data?.equity ?? null}
                />
                <PositionPanel
                  sessionId={replay.session.id}
                  stepCount={replay.stepCount}
                  events={replay.events}
                />
              </div>
            )}
          </div>
        )}

        {step.type === 'action' && !stepDone && (
          <p className="action-hint">Follow the pointer to continue.</p>
        )}

        <footer className="lesson-footer">
          {canAdvance ? (
            <button
              className="btn-primary"
              onClick={() => {
                void (async () => {
                  if (!stepDone && (step.type === 'explain' || step.type === 'replay')) {
                    await markComplete()
                  }
                  await next()
                })()
              }}
            >
              {step.index + 1 < steps.length ? 'Next →' : 'Finish module ✓'}
            </button>
          ) : (
            <span className="lesson-wait">
              {step.type === 'quiz' && 'Answer correctly to continue.'}
              {step.type === 'action' && ''}
              {step.type === 'practice' && 'Mark the practice complete to continue.'}
              {step.type === 'replay' && 'Watch through the scripted pauses to continue.'}
            </span>
          )}
        </footer>
      </div>

      {step.type === 'action' && step.pointer && !stepDone && (
        <GuidedPointer
          target={step.pointer.target}
          label={step.pointer.label}
          onTargetClick={() => void markComplete()}
        />
      )}
    </div>
  )
}
