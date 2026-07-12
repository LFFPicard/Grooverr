const VARIANTS = {
  downloading: 'bg-mustard-tint text-mustard',
  queued: 'bg-panel-sunken text-text-dim border border-border',
  done: 'bg-sage-tint text-sage',
  error: 'bg-danger-tint text-danger',
}

export function Pill({ variant, children, title }) {
  return (
    <span
      title={title}
      className={`inline-block max-w-full text-[0.7rem] font-semibold px-2.5 py-1 rounded-full text-center whitespace-nowrap overflow-hidden text-ellipsis align-middle ${VARIANTS[variant] ?? VARIANTS.queued}`}
    >
      {children}
    </span>
  )
}
