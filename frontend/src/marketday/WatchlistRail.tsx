import type { SymbolStat } from '../lib/types'

function fmtPx(v: number | null): string {
  return v == null ? '—' : v.toFixed(2)
}

function fmtChg(v: number | null): string {
  if (v == null) return ''
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
}

export function WatchlistRail({
  symbols,
  selected,
  onSelect,
}: {
  symbols: SymbolStat[]
  selected: string
  onSelect: (s: string) => void
}) {
  return (
    <aside className="rail" aria-label="Watchlist">
      {symbols.map((s) => (
        <button
          key={s.symbol}
          className={`rail-item ${s.symbol === selected ? 'selected' : ''}`}
          aria-pressed={s.symbol === selected}
          onClick={() => onSelect(s.symbol)}
        >
          <span className="sym">{s.symbol}</span>
          <span className="px">{fmtPx(s.last_price)}</span>
          <span className="sub">RVOL {s.rvol == null ? '–' : s.rvol.toFixed(1)}</span>
          <span className={`chg ${s.change_pct != null && s.change_pct < 0 ? 'down' : 'up'}`}>
            {fmtChg(s.change_pct)}
          </span>
        </button>
      ))}
    </aside>
  )
}
