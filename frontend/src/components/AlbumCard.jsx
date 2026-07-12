export function AlbumCard({ album }) {
  const expected = album.total_tracks || album.known_tracks || 0
  const isComplete = album.completeness === 'complete'
  const badgeClass = isComplete ? 'bg-sage text-white' : 'bg-mustard text-white'
  const missing = expected - album.downloaded_tracks

  return (
    <div className="bg-panel border border-border rounded-card overflow-hidden shadow-card dark:shadow-card-dark">
      <div className="aspect-square bg-gradient-to-br from-plum-tint to-mustard-tint relative">
        {album.cover_art_url && (
          <img src={album.cover_art_url} alt="" loading="lazy" className="w-full h-full object-cover absolute inset-0" />
        )}
        <span className={`absolute top-2.5 right-2.5 font-mono text-[0.65rem] font-semibold px-2 py-0.5 rounded-full ${badgeClass}`}>
          {album.downloaded_tracks}/{expected}
        </span>
      </div>
      <div className="px-4 py-3.5">
        <div className="font-display text-[0.95rem] font-semibold truncate">{album.title}</div>
        <div className="text-[0.78rem] text-text-faint mt-0.5 truncate">{album.artist_name}</div>
        <div className="text-[0.72rem] text-text-dim mt-2.5">
          {album.downloaded_tracks} of {expected} tracks
          {missing > 0 && ` · missing ${missing}`}
        </div>
      </div>
    </div>
  )
}
