import { useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './lib/api'
import { navigate, parseRoute, useAppLocation } from './lib/routing'
import { KeySetup } from './firstrun/KeySetup'
import { FirstFetchGate } from './firstrun/FirstFetchGate'
import { TopBar } from './shell/TopBar'
import { TabNav } from './shell/TabNav'
import { MarketDayTab } from './tabs/MarketDayTab'
import { LearnTab } from './tabs/LearnTab'
import { JournalTab } from './tabs/JournalTab'
import { ErrorState, LoadingState } from './shell/AsyncState'

export default function App() {
  const queryClient = useQueryClient()
  const keys = useQuery({ queryKey: ['keys'], queryFn: api.keysStatus })
  const location = useAppLocation()
  const route = parseRoute(location)

  useEffect(() => {
    const current = window.location.pathname.replace(/\/$/, '') || '/'
    if (current !== route.canonical) {
      navigate(`${route.canonical}${window.location.search}`, { replace: true })
    }
  }, [route.canonical])

  if (keys.isPending) return <div className="boot"><LoadingState label="Connecting to backend" /></div>
  if (keys.isError) {
    return (
      <div className="boot error">
        <ErrorState
          title="Backend unreachable"
          error="Start it with run.ps1 at the repository root (expects http://127.0.0.1:8000)."
          onRetry={() => void keys.refetch()}
        />
      </div>
    )
  }
  if (!keys.data.present) {
    return <KeySetup onDone={() => queryClient.invalidateQueries({ queryKey: ['keys'] })} />
  }

  return (
    <FirstFetchGate>
      <div className="app">
        <TopBar />
        <TabNav tab={route.tab} />
        <main id="main-content">
          {route.tab === 'market' && (
            <MarketDayTab
              phase={route.phase}
              onPhaseChange={(phase) => navigate(`/today/${phase}${window.location.search}`)}
            />
          )}
          {route.tab === 'learn' && (
            <LearnTab
              section={route.section}
              moduleNumber={route.moduleNumber}
              onNavigate={navigate}
            />
          )}
          {route.tab === 'journal' && (
            <JournalTab
              selectedTradeId={route.tradeId}
              onSelectTrade={(id) => navigate(id == null ? '/journal' : `/journal/${id}`)}
              onPractice={() => navigate('/learn/drills')}
            />
          )}
        </main>
      </div>
    </FirstFetchGate>
  )
}
