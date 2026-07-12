import { Pill } from './Pill'

function statusPill(job, compact) {
  if (job.status === 'active' && job.job_type === 'download') {
    return <Pill variant="downloading">{job.progress_percent}%</Pill>
  }
  if (job.status === 'active') {
    return <Pill variant="downloading">Resolving</Pill>
  }
  if (job.status === 'queued') {
    return <Pill variant="queued">Queued</Pill>
  }
  if (job.status === 'done') {
    return <Pill variant="done">Saved</Pill>
  }
  // The compact (Dashboard teaser) pill column is too narrow for an error
  // summary — error jobs never actually appear there anyway (the Active
  // Queue panel only fetches active/queued statuses), but truncate hard
  // as a safety net. The full-width Queue screen gets more room to work with.
  const message = job.error_message || 'Error'
  const limit = compact ? 10 : 26
  const short = message.length > limit ? `${message.slice(0, limit)}…` : message
  return (
    <Pill variant="error" title={job.error_message}>
      {short}
    </Pill>
  )
}

function subtitle(job) {
  if (job.job_type === 'metadata_resolve') {
    if (job.status === 'active') return 'Resolving metadata…'
    if (job.status === 'queued') return 'Waiting to resolve'
    if (job.status === 'error') return job.error_message || 'Metadata resolution failed'
    return 'Metadata resolved'
  }
  const artist = job.artist_name || 'Unknown artist'
  const album = job.album_title || 'Unknown album'
  return `${artist} · ${album}`
}

export function QueueRow({ job, actions }) {
  const progress = job.status === 'done' ? 100 : job.progress_percent || 0
  const barClass = job.status === 'done' ? 'bg-sage' : 'bg-mustard'
  const gridCols = actions ? 'grid-cols-[44px_1fr_130px_180px_auto]' : 'grid-cols-[44px_1fr_130px_92px]'

  return (
    <div className={`grid ${gridCols} items-center gap-3.5 px-5 py-3 border-b border-border last:border-b-0`}>
      <div className="w-11 h-11 rounded-lg bg-gradient-to-br from-plum-tint to-mustard-tint flex-shrink-0" />
      <div className="min-w-0">
        <div className="text-[0.87rem] font-semibold truncate">{job.track_title || 'Unknown track'}</div>
        <div className="text-[0.76rem] text-text-faint mt-0.5 truncate">{subtitle(job)}</div>
      </div>
      <div className="h-1.5 bg-panel-sunken rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${barClass}`} style={{ width: `${progress}%` }} />
      </div>
      <div className="min-w-0 overflow-hidden">{statusPill(job, !actions)}</div>
      {actions && <div className="flex justify-end flex-shrink-0">{actions}</div>}
    </div>
  )
}
