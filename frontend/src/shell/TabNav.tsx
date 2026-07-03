export type Tab = 'market' | 'learn' | 'journal'

const TABS: { id: Tab; label: string }[] = [
  { id: 'market', label: 'Market Day' },
  { id: 'learn', label: 'Learn' },
  { id: 'journal', label: 'Journal' },
]

export function TabNav({ tab, onChange }: { tab: Tab; onChange: (t: Tab) => void }) {
  return (
    <nav className="tabnav">
      {TABS.map((t) => (
        <button
          key={t.id}
          className={tab === t.id ? 'active' : ''}
          onClick={() => onChange(t.id)}
        >
          {t.label}
        </button>
      ))}
    </nav>
  )
}
