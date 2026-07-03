import { useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { BackfillProgress } from './BackfillProgress'

/** After keys exist: make sure the initial backfill has happened before
 * showing the shell (doc §13 — initial fetch with visible progress). */
export function FirstFetchGate({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient()
  const symbols = useQuery({ queryKey: ['symbols'], queryFn: api.symbols })
  const progress = useQuery({
    queryKey: ['backfill'],
    queryFn: api.backfillProgress,
    refetchInterval: (q) => (q.state.data?.state === 'running' ? 1000 : false),
  })
  const kicked = useRef(false)

  const hasData = symbols.data?.symbols.some((s) => s.last_price != null) ?? false
  const state = progress.data?.state ?? 'idle'

  useEffect(() => {
    if (!kicked.current && !hasData && state === 'idle' && symbols.isSuccess) {
      kicked.current = true
      api
        .startBackfill()
        .then(() => queryClient.invalidateQueries({ queryKey: ['backfill'] }))
        .catch(() => {
          kicked.current = false // e.g. another window already started it
          queryClient.invalidateQueries({ queryKey: ['backfill'] })
        })
    }
  }, [hasData, state, symbols.isSuccess, queryClient])

  useEffect(() => {
    if (state === 'done' && !hasData) {
      queryClient.invalidateQueries({ queryKey: ['symbols'] })
    }
  }, [state, hasData, queryClient])

  if (hasData) return <>{children}</>
  if (symbols.isPending || (state === 'idle' && !kicked.current)) {
    return <div className="boot">Checking local data…</div>
  }
  return <BackfillProgress info={progress.data} />
}
