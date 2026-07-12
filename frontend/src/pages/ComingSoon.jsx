export default function ComingSoon({ title, batch }) {
  return (
    <div className="bg-panel border border-border rounded-card px-8 py-16 text-center shadow-card dark:shadow-card-dark">
      <h1 className="font-display text-2xl font-semibold mb-2">{title}</h1>
      <p className="text-text-dim text-[0.9rem]">Coming in Batch {batch}.</p>
    </div>
  )
}
