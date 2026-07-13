import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { WorkoutItem } from '../lib/types'
import { ErrorState, LoadingState } from '../shell/AsyncState'

export function DailyWorkoutCard({ onStart }: { onStart: (item: WorkoutItem, runId: number) => void }) {
  const workoutQ = useQuery({ queryKey: ['dailyWorkout'], queryFn: api.dailyWorkout, staleTime: 30_000 })
  const workout = workoutQ.data
  if (workoutQ.isPending) return <section className="daily-workout"><LoadingState label="Building today’s workout" /></section>
  if (workoutQ.isError) return <section className="daily-workout"><ErrorState title="Could not build today’s workout" error={workoutQ.error} onRetry={() => void workoutQ.refetch()} /></section>
  if (!workout?.unlocked) return <section className="daily-workout"><h2>Today’s workout</h2><p className="muted">Complete Module {workout?.gate_module ?? 8} to unlock adaptive setup reps.</p></section>
  if (!workout.run) return null
  const done = workout.items.filter((item) => item.status === 'complete').length
  return <section className="daily-workout">
    <div className="workout-title"><div><h2>Today’s workout</h2><p className="muted">{done}/{workout.items.length} blocks complete · recommendations update from your decisions and reviews.</p></div>{workout.run.status === 'complete' && <span className="workout-complete">✓ Complete</span>}</div>
    <div className="workout-items">{workout.items.map((item) => <article key={item.id} className={`workout-item ${item.status}`}>
      <span className="workout-rank">{item.position + 1}</span><div><strong>{item.label}</strong><p>{item.reason}</p><span className="muted">{item.reps} blind reps · weakness {item.weakness_score.toFixed(2)}</span></div>
      {item.status === 'complete' ? <span className="workout-check">✓</span> : <button className="btn-primary" onClick={() => onStart(item, workout.run!.id)}>Start</button>}
    </article>)}</div>
  </section>
}
