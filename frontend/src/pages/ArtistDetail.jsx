import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useAddEntireDiscography, useArtistDiscography } from '../api/hooks'
import { DiscographyCard } from '../components/DiscographyCard'
import { VirtualizedCardGrid } from '../components/VirtualizedCardGrid'

function AddEntireDiscographyButton({ artistId }) {
  const mutation = useAddEntireDiscography()
  const [result, setResult] = useState(null)

  if (mutation.isPending) {
    return (
      <button disabled className="btn bg-panel-sunken border border-border text-text-dim">
        Adding everything… this can take a little while
      </button>
    )
  }
  if (result) {
    return (
      <button disabled className="btn bg-sage-tint text-sage">
        {result.albums_added} releases added ✓ · {result.queued_jobs} queued
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

export default function ArtistDetail() {
  const { artistId } = useParams()
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading, isError } =
    useArtistDiscography(artistId)
  const items = useMemo(() => data?.pages.flatMap((page) => page.items) ?? [], [data])
  const total = data?.pages[0]?.total
  const artistName = items[0]?.album.artist_name

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
        {items.length > 0 && <AddEntireDiscographyButton artistId={artistId} />}
      </div>

      <VirtualizedCardGrid
        items={items}
        isLoading={isLoading}
        isError={isError}
        hasNextPage={hasNextPage}
        isFetchingNextPage={isFetchingNextPage}
        fetchNextPage={fetchNextPage}
        renderCard={(item) => <DiscographyCard key={item.release_group_id} item={item} />}
        emptyMessage="No official releases found for this artist on MusicBrainz."
        errorMessage="Could not load this artist's discography."
      />
    </div>
  )
}
