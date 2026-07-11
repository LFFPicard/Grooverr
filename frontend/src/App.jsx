import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'

function useTheme() {
  const [theme, setTheme] = useState(() => localStorage.getItem('grooverr-theme') || 'light')

  useEffect(() => {
    document.body.dataset.theme = theme
    localStorage.setItem('grooverr-theme', theme)
  }, [theme])

  return [theme, () => setTheme(t => (t === 'light' ? 'dark' : 'light'))]
}

function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: () => fetch('/api/health').then(r => r.json()),
  })
}

export default function App() {
  const [theme, toggleTheme] = useTheme()
  const { data, isLoading, isError } = useHealth()

  return (
    <div className="min-h-screen bg-bg text-text font-body">
      <header className="flex items-center gap-5 px-8 py-4 border-b border-border bg-panel">
        <div className="flex items-center gap-2 font-display text-xl font-semibold">
          <span className="w-8 h-8 rounded-full bg-plum text-white grid place-items-center font-display text-sm">
            G
          </span>
          Grooverr
        </div>
        <button
          onClick={toggleTheme}
          className="ml-auto w-9 h-9 rounded-full border border-border bg-panel-sunken text-text-dim grid place-items-center"
        >
          ◐
        </button>
      </header>

      <main className="max-w-3xl mx-auto px-8 py-16 text-center">
        <h1 className="font-display text-3xl font-semibold mb-3">
          Batch 1 — Scaffolding
        </h1>
        <p className="text-text-dim mb-8">
          Backend + frontend are wired up. Design tokens loaded. API connectivity below.
        </p>

        <div className="inline-block bg-panel border border-border rounded-card shadow-card px-6 py-4 text-left">
          <div className="text-xs font-semibold uppercase tracking-wide text-text-faint mb-1">
            Backend health check
          </div>
          {isLoading && <div className="font-mono text-sm text-text-dim">Checking…</div>}
          {isError && <div className="font-mono text-sm text-danger">Could not reach /api/health</div>}
          {data && (
            <div className="font-mono text-sm text-sage">
              status: {data.status} · service: {data.service}
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
