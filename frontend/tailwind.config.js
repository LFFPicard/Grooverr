/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  darkMode: '[data-theme="dark"]',
  theme: {
    extend: {
      colors: {
        bg: 'var(--bg)',
        panel: 'var(--panel)',
        'panel-sunken': 'var(--panel-sunken)',
        border: 'var(--border)',
        'border-hi': 'var(--border-hi)',
        plum: { DEFAULT: 'var(--plum)', tint: 'var(--plum-tint)' },
        mustard: { DEFAULT: 'var(--mustard)', tint: 'var(--mustard-tint)' },
        sage: { DEFAULT: 'var(--sage)', tint: 'var(--sage-tint)' },
        danger: { DEFAULT: 'var(--red)', tint: 'var(--red-tint)' },
        text: { DEFAULT: 'var(--text)', dim: 'var(--text-dim)', faint: 'var(--text-faint)' },
      },
      fontFamily: {
        display: ['Fraunces', 'serif'],
        body: ['Inter', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'monospace'],
      },
      borderRadius: {
        card: '14px',
      },
      boxShadow: {
        card: '0 10px 24px -14px rgba(38,35,32,0.18)',
        'card-dark': '0 10px 24px -14px rgba(0,0,0,0.5)',
      },
    },
  },
  plugins: [],
}
