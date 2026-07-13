import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

const STATE_LABEL: Record<string, string> = {
  pre: 'Pre-market',
  open: 'Market open',
  post: 'After hours',
  closed: 'Market closed',
  unknown: '—',
}

export function TopBar() {
  const symbols = useQuery({
    queryKey: ['symbols'],
    queryFn: api.symbols,
    refetchInterval: 60_000,
  })
  const state = symbols.data?.state ?? 'unknown'
  return (
    <header className="topbar">
      <span className="title">
        <span className="title-full">Day Trading Trainer</span>
        <span className="title-short">Trading Trainer</span>
      </span>
      <span className={`state-chip ${state}`} aria-live="polite">{STATE_LABEL[state] ?? state}</span>
      <span className="spacer" />
      <span className="equity">Training simulator</span>
    </header>
  )
}
