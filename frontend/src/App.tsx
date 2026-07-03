import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './lib/api'
import { KeySetup } from './firstrun/KeySetup'
import { FirstFetchGate } from './firstrun/FirstFetchGate'
import { TopBar } from './shell/TopBar'
import { TabNav, type Tab } from './shell/TabNav'
import { MarketDayTab } from './tabs/MarketDayTab'
import { LearnTab } from './tabs/LearnTab'
import { JournalTab } from './tabs/JournalTab'

export default function App() {
  const queryClient = useQueryClient()
  const keys = useQuery({ queryKey: ['keys'], queryFn: api.keysStatus })
  const [tab, setTab] = useState<Tab>('market')

  if (keys.isPending) return <div className="boot">Connecting to backend…</div>
  if (keys.isError) {
    return (
      <div className="boot error">
        Backend unreachable — start it with backend\run.ps1 (expects http://127.0.0.1:8000).
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
        <TabNav tab={tab} onChange={setTab} />
        <main>
          {tab === 'market' && <MarketDayTab />}
          {tab === 'learn' && <LearnTab />}
          {tab === 'journal' && <JournalTab />}
        </main>
      </div>
    </FirstFetchGate>
  )
}
