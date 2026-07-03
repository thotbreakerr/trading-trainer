import type { BackfillProgressInfo } from '../lib/types'

export function BackfillProgress({ info }: { info: BackfillProgressInfo | undefined }) {
  const done = info?.symbols_done ?? 0
  const total = info?.total_symbols ?? 0
  const pct = total > 0 ? Math.round((done / total) * 100) : 5
  return (
    <div className="firstrun">
      <div className="card">
        <h1>Fetching market history</h1>
        <p>
          Downloading the watchlist&apos;s last 30 trading days of minute bars — this runs
          once; every day you load afterwards is cached forever.
        </p>
        <div className="progress-track">
          <div className="progress-fill" style={{ width: `${Math.max(pct, 5)}%` }} />
        </div>
        <div className="progress-note">
          {info?.state === 'error'
            ? `Failed: ${info.error ?? 'unknown error'} — restart the backend to retry`
            : info?.current
              ? `${info.current} (${done}/${total} symbols)`
              : 'Starting…'}
        </div>
        {info?.errors && info.errors.length > 0 && (
          <div className="warn-list">
            {info.errors.map((w, i) => (
              <div key={i}>⚠ {w}</div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
