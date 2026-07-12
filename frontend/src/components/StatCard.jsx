const ACCENTS = {
  mustard: 'border-l-mustard',
  faint: 'border-l-text-faint',
  sage: 'border-l-sage',
  danger: 'border-l-danger',
}

export function StatCard({ label, value, sub, accent = 'mustard' }) {
  return (
    <div
      className={`bg-panel border border-border rounded-card px-5 py-5 shadow-card dark:shadow-card-dark border-l-[3px] ${ACCENTS[accent] ?? ACCENTS.mustard}`}
    >
      <div className="text-[0.72rem] text-text-faint uppercase tracking-wider font-semibold">{label}</div>
      <div className="font-display text-3xl font-semibold mt-1">{value}</div>
      {sub && <div className="text-[0.78rem] text-text-dim mt-1">{sub}</div>}
    </div>
  )
}
