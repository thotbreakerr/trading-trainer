import { useState } from 'react'
import type { CalloutData } from '../lib/types'

const etTime = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  hour: 'numeric',
  minute: '2-digit',
})

function firedAt(c: CalloutData): string {
  return etTime.format(new Date(c.fired_ts))
}

export function LockedCard({ callout }: { callout: CalloutData }) {
  return (
    <div className="callout-card locked-card">
      <span className="lock-icon">🔒</span>
      <div>
        <div className="locked-title">
          <em>Something</em> fired on {callout.symbol} at {firedAt(callout)} ET
        </div>
        <div className="locked-sub">
          unlocks in Module {callout.unlock_module ?? '—'}
        </div>
      </div>
    </div>
  )
}

export function CalloutCard({
  callout,
  tradingUnlocked,
  onAct,
}: {
  callout: CalloutData
  tradingUnlocked: boolean
  onAct: (id: string) => Promise<void>
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showChecklist, setShowChecklist] = useState(false)
  if (callout.locked) return <LockedCard callout={callout} />

  const seconds = callout.watch_seconds_left ?? 0
  const mm = Math.floor(seconds / 60)
  const ss = String(seconds % 60).padStart(2, '0')
  const tier = callout.grade?.tier

  const act = async () => {
    setBusy(true)
    setError(null)
    try {
      await onAct(callout.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={`callout-card status-${callout.status}`}>
      <div className="callout-head">
        <strong>{callout.symbol}</strong>
        <span className="callout-type">
          {callout.setup_type?.replace(/_/g, ' ')} · {callout.direction}
        </span>
        {tier && (
          <button
            className={`grade-chip ${tier.toLowerCase()}`}
            onClick={() => setShowChecklist((s) => !s)}
            title="Show the checklist"
          >
            {tier}
          </button>
        )}
      </div>
      {callout.entry != null && (
        <div className="callout-prices">
          entry {callout.entry?.toFixed(2)} · stop {callout.stop?.toFixed(2)} · target{' '}
          {callout.target?.toFixed(2)} · R:R {callout.rr ?? '—'}
        </div>
      )}
      {showChecklist && callout.grade && (
        <ul className="grade-checklist">
          {callout.grade.checklist.map((c) => (
            <li key={c.key} className={c.passed ? 'pass' : 'fail'} title={c.detail}>
              {c.passed ? '✓' : '✗'} {c.label}
            </li>
          ))}
        </ul>
      )}
      {callout.grade?.note && <div className="grade-note">{callout.grade.note}</div>}

      {callout.status === 'watching' && (
        <div className="callout-foot">
          <span className="countdown">
            watching {mm}:{ss}
          </span>
          {callout.tradeable && (
            <button
              className="btn-primary act"
              disabled={busy || !tradingUnlocked}
              title={tradingUnlocked ? '' : 'Trading unlocks after Module 9'}
              onClick={() => void act()}
            >
              Act — bracket
            </button>
          )}
        </div>
      )}
      {callout.status === 'invalidated' && (
        <div className="invalidated-note">{callout.invalidated_reason}</div>
      )}
      {callout.status === 'expired' && <div className="muted">expired to the day's log</div>}
      {callout.status === 'acted' && <div className="acted-note">✓ acted — see positions</div>}
      {callout.outcome && (
        <div className="muted">
          hindsight: {callout.outcome}
          {callout.outcome_r != null ? ` (${callout.outcome_r > 0 ? '+' : ''}${callout.outcome_r}R)` : ''}
        </div>
      )}
      {error && <div className="ticket-error">{error}</div>}
      <div className="callout-fired muted">fired {firedAt(callout)} ET</div>
    </div>
  )
}
