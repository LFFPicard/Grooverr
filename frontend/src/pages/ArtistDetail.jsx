import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useAddEntireDiscography, useArtistDiscography, useDeleteArtist } from '../api/hooks'
import { ConfirmDeleteModal } from '../components/ConfirmDeleteModal'
import { DiscographyCard } from '../components/DiscographyCard'
import { VirtualizedCardGrid } from '../components/VirtualizedCardGrid'

// Section 7.1.1 (strengthened 2026-07-15): segmented filter tabs, same
// pattern as Library's Albums/Playlists tabs — a mixed 10+ release
// discography is unnavigable with only the per-card corner badge.
const TYPE_TABS = [
  { key: 'all', label: 'All' },
  { key: 'album', label: 'Album' },
  { key: 'single', label: 'Single' },
  { key: 'ep', label: 'EP' },
  { key: 'compilation', label: 'Compilation' },
]

function AddEntireDiscographyButton({ artistId }) {
  const mutation = useAddEntireDiscography()
  const [result, setResult] = useState(null)

  if (mutation.isPending) {
    return (
      <button disabled className="btn bg-panel-sunken border border-border text-text-dim">
        Adding…
      </button>
    )
  }
  if (result) {
    // Post-audit (Section 11 item 15): the request now returns as soon as
    // per-release jobs are enqueued, not once they're actually added —
    // real progress shows up in the Queue screen (Section 7.5) as each
    // release resolves, same as any other batch of adds.
    return (
      <button disabled className="btn bg-sage-tint text-sage">
        {result.jobs_enqueued} queued ✓ · {result.already_in_library} already in library — see Queue for progress
      </button>
    )
  }
  if (mutation.isError) {
    return (
      <button
        onClick={() => mutation.mutate(artistId, { onSuccess: setResult })}
        title={mutation.error.message}
        className="btn bg-danger-tint text-danger"
      >
        Failed — retry
      </button>
    )
  }
  return (
    <button onClick={() => mutation.mutate(artistId, { onSuccess: setResult })} className="btn btn-plum">
      Add entire discography
    </button>
  )
}

function DeleteArtistButton({ artistId, artistName }) {
  const [open, setOpen] = useState(false)
  const mutation = useDeleteArtist()
  const navigate = useNavigate()

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="btn bg-panel-sunken border border-border text-danger text-[0.8rem] px-3 py-1.5"
      >
        Delete artist
      </button>
      <ConfirmDeleteModal
        open={open}
        busy={mutation.isPending}
        title={`Delete “${artistName || 'this artist'}”?`}
        description="This removes the artist, every album, and every track from your library. Choose whether to also delete the real audio files from disk — this cannot be undone."
        onCancel={() => setOpen(false)}
        onConfirm={(deleteFiles) =>
          mutation.mutate(
            { artistId, deleteFiles },
            { onSuccess: () => navigate('/library') }
          )
        }
      />
    </>
  )
}

export default function ArtistDetail() {
  const { artistId } = useParams()
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading, isError } =
    useArtistDiscography(artistId)
  const items = useMemo(() => data?.pages.flatMap((page) => page.items) ?? [], [data])
  const total = data?.pages[0]?.total
  const artistName = items[0]?.album.artist_name

  const [typeTab, setTypeTab] = useState('all')
  const filteredItems = useMemo(
    () => (typeTab === 'all' ? items : items.filter((item) => item.album.album_type === typeTab)),
    [items, typeTab]
  )

  return (
    <div>
      <Link to="/search" className="text-[0.8rem] text-text-faint hover:text-text mb-5 inline-block">
        ← Search
      </Link>

      <div className="flex items-center justify-between gap-4 mb-6 flex-wrap">
        <div>
          <h1 className="font-display text-2xl font-semibold">{artistName || 'Artist'}</h1>
          <div className="text-[0.8rem] text-text-faint mt-1">
            Browsed directly from MusicBrainz — one-time snapshot, not a standing watch for new releases.
            {typeof total === 'number' && ` ${total} release${total === 1 ? '' : 's'}.`}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <DeleteArtistButton artistId={artistId} artistName={artistName} />
          {items.length > 0 && <AddEntireDiscographyButton artistId={artistId} />}
        </div>
      </div>

      <div className="flex items-center gap-2 mb-6">
        {TYPE_TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTypeTab(t.key)}
            className={`text-[0.85rem] font-medium px-4 py-2 rounded-full transition-colors ${
              typeTab === t.key
                ? 'text-plum bg-plum-tint font-semibold'
                : 'text-text-dim bg-panel-sunken border border-border hover:text-text'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <VirtualizedCardGrid
        items={filteredItems}
        isLoading={isLoading}
        isError={isError}
        hasNextPage={hasNextPage}
        isFetchingNextPage={isFetchingNextPage}
        fetchNextPage={fetchNextPage}
        renderCard={(item) => <DiscographyCard key={item.release_group_id} item={item} />}
        emptyMessage={
          typeTab === 'all'
            ? "No official releases found for this artist on MusicBrainz."
            : `No ${typeTab === 'ep' ? 'EPs' : typeTab + 's'} found for this artist.`
        }
        errorMessage="Could not load this artist's discography."
      />
    </div>
  )
}
