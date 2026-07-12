export function Panel({ title, tag, children, className = '' }) {
  return (
    <div className={`bg-panel border border-border rounded-card overflow-hidden shadow-card dark:shadow-card-dark ${className}`}>
      {(title || tag) && (
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          {title && <h3 className="font-display text-base font-semibold">{title}</h3>}
          {tag && (
            <span className="text-[0.7rem] text-text-faint bg-panel-sunken border border-border px-2.5 py-0.5 rounded-full">
              {tag}
            </span>
          )}
        </div>
      )}
      {children}
    </div>
  )
}
