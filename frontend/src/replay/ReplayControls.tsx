import type { Speed } from './useReplaySession'

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

const SPEEDS: Speed[] = [1, 2, 5]

export function ReplayControls({
  clock,
  playing,
  speed,
  done,
  onPlayPause,
  onStepOne,
  onSpeed,
  onRestart,
  onExit,
}: {
  clock: number | null
  playing: boolean
  speed: Speed
  done: boolean
  onPlayPause: () => void
  onStepOne: () => void
  onSpeed: (s: Speed) => void
  onRestart: () => void
  onExit: () => void
}) {
  const when = clock ? new Date(clock * 1000) : null
  return (
    <div className="replay-controls">
      <span className="replay-chip">REPLAY</span>
      {when && (
        <span className="replay-clock">
          {ct.format(when)} CT <span className="et">({et.format(when)} ET)</span>
        </span>
      )}
      {done && <span className="replay-done">session close</span>}
      <button onClick={onPlayPause} disabled={done} title={playing ? 'Pause' : 'Play'} aria-label={playing ? 'Pause replay' : 'Play replay'}>
        {playing ? '⏸' : '▶'}
      </button>
      <button onClick={onStepOne} disabled={playing || done} title="Step one bar" aria-label="Step one bar">
        +1
      </button>
      <div className="speed-group" aria-label="Replay speed">
        {SPEEDS.map((s) => (
          <button
            key={s}
            className={s === speed ? 'active' : ''}
            aria-pressed={s === speed}
            onClick={() => onSpeed(s)}
          >
            {s}×
          </button>
        ))}
      </div>
      <button onClick={onRestart} title="Restart the day (no rewind)" aria-label="Restart replay">
        ↺ restart
      </button>
      <button onClick={onExit} title="Exit replay" aria-label="Exit replay">
        ✕
      </button>
    </div>
  )
}
