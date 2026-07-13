import { handleAppLink, type PrimaryTab } from '../lib/routing'

const TABS: { id: PrimaryTab; label: string; href: string }[] = [
  { id: 'market', label: 'Market Day', href: '/today/trade' },
  { id: 'learn', label: 'Learn', href: '/learn/today' },
  { id: 'journal', label: 'Journal', href: '/journal' },
]

export function TabNav({ tab }: { tab: PrimaryTab }) {
  return (
    <nav className="tabnav" aria-label="Primary navigation">
      {TABS.map((item) => (
        <a
          key={item.id}
          href={item.href}
          className={tab === item.id ? 'active' : ''}
          aria-current={tab === item.id ? 'page' : undefined}
          onClick={(event) => handleAppLink(event, item.href)}
        >
          {item.label}
        </a>
      ))}
    </nav>
  )
}
