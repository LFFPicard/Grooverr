import { AddButton } from './AddButton'
import { SourceTag } from './SourceTag'

export function AlbumResultCard({ album }) {
  const meta = [album.artist_name, album.release_year].filter(Boolean).join(' · ')

  return (
    <div className="flex items-center gap-4 bg-panel border border-border rounded-card px-5 py-4 shadow-card dark:shadow-card-dark">
      <div className="w-12 h-12 rounded-lg bg-gradient-to-br from-plum-tint to-mustard-tint flex-shrink-0 overflow-hidden">
        {album.cover_art_url && (
          <img src={album.cover_art_url} alt="" loading="lazy" className="w-full h-full object-cover" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="font-display text-[0.95rem] font-semibold truncate">{album.title}</div>
        <div className="text-[0.8rem] text-text-faint mt-0.5 truncate">
          {meta}
          {album.total_tracks && <span className="font-mono text-text-dim"> · {album.total_tracks} tracks</span>}
        </div>
      </div>
      <SourceTag source={album.source} />
      <AddButton payload={{ type: 'album', album }} />
    </div>
  )
}
