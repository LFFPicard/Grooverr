import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useTheme } from '../hooks/useTheme'

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/search', label: 'Search' },
  { to: '/library', label: 'Library' },
  { to: '/queue', label: 'Queue' },
  { to: '/settings', label: 'Settings' },
]

export function Layout({ children }) {
  const [, toggleTheme] = useTheme()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')

  function handleSubmit(event) {
    event.preventDefault()
    const q = query.trim()
    if (q) navigate(`/search?q=${encodeURIComponent(q)}`)
  }

  return (
    <div className="min-h-screen bg-bg text-text font-body">
      <header className="flex items-center gap-5 px-8 py-4 border-b border-border bg-panel">
        <div className="flex items-center gap-2.5 font-display text-xl font-semibold tracking-tight">
          <span className="w-8 h-8 rounded-full bg-plum text-white grid place-items-center font-display text-sm">
            G
          </span>
          Grooverr
        </div>

        <nav className="flex gap-1.5 ml-5">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `text-[0.85rem] font-medium px-3.5 py-2 rounded-full transition-colors ${
                  isActive ? 'text-plum bg-plum-tint font-semibold' : 'text-text-dim hover:text-text'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-3">
          <form
            onSubmit={handleSubmit}
            className="flex items-center gap-2 bg-panel-sunken border border-border rounded-full px-4 py-2 w-[360px]"
          >
            <span aria-hidden="true">🔍</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search MusicBrainz, YouTube Music, or paste a link…"
              className="bg-transparent outline-none text-text placeholder:text-text-faint text-[0.85rem] w-full"
            />
          </form>
          <button
            type="button"
            onClick={toggleTheme}
            aria-label="Toggle theme"
            className="w-9 h-9 rounded-full border border-border bg-panel-sunken text-text-dim grid place-items-center flex-shrink-0"
          >
            ◐
          </button>
        </div>
      </header>

      <main className="px-10 py-8 max-w-[1320px] mx-auto">{children}</main>
    </div>
  )
}
