import type { Timeframe } from '../lib/types'

const TFS: Timeframe[] = ['1m', '5m', '15m', '1h']

export function TimeframeSwitcher({
  tf,
  onChange,
}: {
  tf: Timeframe
  onChange: (tf: Timeframe) => void
}) {
  return (
    <div className="tf-switcher" aria-label="Chart timeframe">
      {TFS.map((t) => (
        <button
          key={t}
          data-pointer-id={`tf-${t}`}
          className={t === tf ? 'active' : ''}
          aria-pressed={t === tf}
          aria-label={`${t} timeframe`}
          onClick={() => onChange(t)}
        >
          {t}
        </button>
      ))}
    </div>
  )
}
