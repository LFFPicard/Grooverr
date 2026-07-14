import { LibraryCard } from './LibraryCard'

export function AlbumCard({ album }) {
  return (
    <LibraryCard
      title={album.title}
      subtitle={album.artist_name}
      coverArtUrl={album.cover_art_url}
      downloadedTracks={album.downloaded_tracks}
      expectedTracks={album.total_tracks || album.known_tracks || 0}
      completeness={album.completeness}
      to={`/library/album/${album.id}`}
    />
  )
}
