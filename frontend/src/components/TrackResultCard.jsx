import { AddButton } from './AddButton'
import { SourceTag } from './SourceTag'

function formatDuration(seconds) {
  if (!seconds) return null
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export function TrackResultCard({ track }) {
  const duration = formatDuration(track.duration_seconds)
  const meta = [track.artist_name, track.album_title].filter(Boolean).join(' · ')

  return (
    <div className="flex items-center gap-4 bg-panel border border-border rounded-card px-5 py-4 shadow-card dark:shadow-card-dark">
      <div className="w-12 h-12 rounded-lg bg-gradient-to-br from-plum-tint to-mustard-tint flex-shrink-0 overflow-hidden">
        {track.cover_art_url && (
          <img src={track.cover_art_url} alt="" loading="lazy" className="w-full h-full object-cover" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="font-display text-[0.95rem] font-semibold truncate">{track.title}</div>
        <div className="text-[0.8rem] text-text-faint mt-0.5 truncate">
          {meta}
          {duration && <span className="font-mono text-text-dim"> · {duration}</span>}
        </div>
      </div>
      <SourceTag source={track.source} />
      <AddButton payload={{ type: 'track', track }} />
    </div>
  )
}
