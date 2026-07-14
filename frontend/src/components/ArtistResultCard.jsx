import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAddToLibrary } from '../api/hooks'
import { AddButton } from './AddButton'
import { SourceTag } from './SourceTag'

/**
 * Artist mode's cards click through to Artist Detail (Section 7.1.1) — the
 * primary path for "show me everything by this artist" (Section 7.1 step 4).
 * All/Title/Album modes keep today's behavior: an Add-to-library button
 * only, no navigation (Section 7.1 step 5). The Add button itself always
 * stays a separate, row-only action per Section 3, whichever mode this
 * renders in — clicking it never navigates.
 */
export function ArtistResultCard({ artist, linkToDetail = false }) {
  const navigate = useNavigate()
  const addToLibrary = useAddToLibrary()
  const [opening, setOpening] = useState(false)

  function handleCardClick() {
    if (!linkToDetail || opening) return
    setOpening(true)
    addToLibrary.mutate(
      { type: 'artist', artist },
      {
        onSuccess: (result) => navigate(`/artist/${result.added_artist_id}`),
        onError: () => setOpening(false),
      }
    )
  }

  return (
    <div
      onClick={handleCardClick}
      className={`flex items-center gap-4 bg-panel border border-border rounded-card px-5 py-4 shadow-card dark:shadow-card-dark ${
        linkToDetail ? 'cursor-pointer transition-transform hover:-translate-y-0.5' : ''
      }`}
    >
      <div className="w-12 h-12 rounded-full bg-gradient-to-br from-plum-tint to-mustard-tint flex-shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="font-display text-[0.95rem] font-semibold truncate">{artist.name}</div>
        {linkToDetail && (
          <div className="text-[0.75rem] text-text-faint mt-0.5">
            {opening ? 'Opening discography…' : 'View full discography →'}
          </div>
        )}
      </div>
      <SourceTag source={artist.source} />
      <div onClick={(event) => event.stopPropagation()}>
        <AddButton payload={{ type: 'artist', artist }} />
      </div>
    </div>
  )
}
