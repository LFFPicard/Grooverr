import { AddButton } from './AddButton'
import { SourceTag } from './SourceTag'

export function PlaylistResultCard({ playlist }) {
  const meta = [playlist.author, playlist.total_tracks && `${playlist.total_tracks} tracks`]
    .filter(Boolean)
    .join(' · ')

  return (
    <div className="flex items-center gap-4 bg-panel border border-border rounded-card px-5 py-4 shadow-card dark:shadow-card-dark">
      <div className="w-12 h-12 rounded-lg bg-gradient-to-br from-plum-tint to-mustard-tint flex-shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="font-display text-[0.95rem] font-semibold truncate">{playlist.title}</div>
        <div className="text-[0.8rem] text-text-faint mt-0.5 truncate">{meta}</div>
      </div>
      <SourceTag source={playlist.source} />
      <AddButton payload={{ type: 'playlist', playlist }} label="Add all to library" />
    </div>
  )
}
