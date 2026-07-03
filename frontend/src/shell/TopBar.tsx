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
      <span className="title">Day Trading Trainer</span>
      <span className={`state-chip ${state}`}>{STATE_LABEL[state] ?? state}</span>
      <span className="spacer" />
      {/* paper equity becomes live with the sim engine */}
      <span className="equity">$30,000.00 paper</span>
    </header>
  )
}
