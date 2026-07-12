import { useEffect, useState } from 'react'

export function useTheme() {
  const [theme, setTheme] = useState(() => localStorage.getItem('grooverr-theme') || 'light')

  useEffect(() => {
    document.body.dataset.theme = theme
    localStorage.setItem('grooverr-theme', theme)
  }, [theme])

  const toggle = () => setTheme((t) => (t === 'light' ? 'dark' : 'light'))
  return [theme, toggle]
}
