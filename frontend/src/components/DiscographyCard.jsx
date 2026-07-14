import { AddButton } from './AddButton'

/**
 * Artist Detail's release grid card (Section 7.1.1) — reuses the Library
 * album-card shell, but a discography item isn't a Library album yet: no
 * completeness badge (browse doesn't know the track count until added), just
 * an "Add to library" action, or a "✓ In library" indicator once it is.
 */
export function DiscographyCard({ item }) {
  const { album, in_library: inLibrary } = item

  return (
    <div className="bg-panel border border-border rounded-card overflow-hidden shadow-card dark:shadow-card-dark">
      <div className="aspect-square bg-gradient-to-br from-plum-tint to-mustard-tint relative">
        {album.cover_art_url && (
          <img src={album.cover_art_url} alt="" loading="lazy" className="w-full h-full object-cover absolute inset-0" />
        )}
        {album.album_type && (
          <span className="absolute top-2.5 right-2.5 font-mono text-[0.65rem] font-semibold px-2 py-0.5 rounded-full bg-panel/90 text-text-dim capitalize">
            {album.album_type}
          </span>
        )}
      </div>
      <div className="px-4 py-3.5">
        <div className="font-display text-[0.95rem] font-semibold truncate">{album.title}</div>
        <div className="text-[0.78rem] text-text-faint mt-0.5 truncate">
          {album.release_year || ' '}
        </div>
        <div className="mt-2.5">
          {inLibrary ? (
            <span className="text-[0.8rem] text-sage font-semibold">✓ In library</span>
          ) : (
            <AddButton payload={{ type: 'album', album }} label="Add to library" />
          )}
        </div>
      </div>
    </div>
  )
}
