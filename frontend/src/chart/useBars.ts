import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { Timeframe } from '../lib/types'

export function useBars(symbol: string, day: string | null | undefined, tf: Timeframe) {
  return useQuery({
    queryKey: ['bars', symbol, day, tf],
    queryFn: () => api.bars(symbol, day!, tf),
    enabled: !!day,
    staleTime: 30_000,
  })
}
