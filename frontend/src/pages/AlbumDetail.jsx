import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useAlbumDetail, useCompleteAlbum, useDeleteAlbum } from '../api/hooks'
import { ConfirmDeleteModal } from '../components/ConfirmDeleteModal'
import { TrackRow } from '../components/TrackRow'

function CompleteAlbumButton({ albumId }) {
  const mutation = useCompleteAlbum()
  const [result, setResult] = useState(null)

  if (mutation.isPending) {
    return (
      <button disabled className="btn bg-panel-sunken border border-border text-text-dim">
        Queuing…
      </button>
    )
  }
  if (result) {
    return (
      <button disabled className="btn bg-sage-tint text-sage">
        {result.queued_jobs} queued ✓
      </button>
    )
  }
  return (
    <button onClick={() => mutation.mutate(albumId, { onSuccess: setResult })} className="btn btn-plum">
      Complete this album
    </button>
  )
}

function DeleteAlbumButton({ album }) {
  const [open, setOpen] = useState(false)
  const mutation = useDeleteAlbum()
  const navigate = useNavigate()

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="btn bg-panel-sunken border border-border text-danger text-[0.8rem] px-3 py-1.5"
      >
        Delete album
      </button>
      <ConfirmDeleteModal
        open={open}
        busy={mutation.isPending}
        title={`Delete “${album.title}”?`}
        description="This removes the album and all its tracks from your library. Choose whether to also delete the real audio files from disk — this cannot be undone."
        onCancel={() => setOpen(false)}
        onConfirm={(deleteFiles) =>
          mutation.mutate(
            { albumId: album.id, deleteFiles },
            { onSuccess: () => navigate('/library') }
          )
        }
      />
    </>
  )
}

export default function AlbumDetail() {
  const { albumId } = useParams()
  const { data: album, isLoading, isError } = useAlbumDetail(albumId)

  if (isLoading) {
    return <div className="text-center text-text-faint text-[0.9rem] py-16">Loading…</div>
  }
  if (isError || !album) {
    return (
      <div className="text-center text-danger text-[0.9rem] py-16">
        Could not load this album. <Link to="/library" className="underline">Back to Library</Link>
      </div>
    )
  }

  const multiDisc = album.tracks.some((t) => (t.disc_number || 1) > 1)
  const isComplete = album.completeness === 'complete'

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <Link to="/library" className="text-[0.8rem] text-text-faint hover:text-text inline-block">
          ← Library
        </Link>
        <DeleteAlbumButton album={album} />
      </div>

      <div className="flex gap-6 mb-8">
        <div className="w-40 h-40 rounded-card bg-gradient-to-br from-plum-tint to-mustard-tint flex-shrink-0 overflow-hidden shadow-card dark:shadow-card-dark">
          {album.cover_art_url && (
            <img src={album.cover_art_url} alt="" className="w-full h-full object-cover" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <h1 className="font-display text-2xl font-semibold truncate">{album.title}</h1>
          <div className="text-text-dim text-[0.95rem] mt-1">{album.artist_name}</div>
          <div className="text-text-faint text-[0.82rem] mt-2 flex gap-2 flex-wrap">
            {album.release_year && <span>{album.release_year}</span>}
            {album.genre && <span>· {album.genre}</span>}
            <span>· {album.album_type}</span>
            <span className="font-mono">
              · {album.downloaded_tracks} of {album.total_tracks ?? album.known_tracks} tracks
            </span>
          </div>
          <div className="mt-5">
            {isComplete ? (
              <span className="text-[0.82rem] text-sage font-semibold">✓ Complete</span>
            ) : (
              <CompleteAlbumButton albumId={album.id} />
            )}
          </div>
        </div>
      </div>

      <div className="bg-panel border border-border rounded-card overflow-hidden shadow-card dark:shadow-card-dark">
        {album.tracks.length === 0 ? (
          <div className="px-5 py-8 text-center text-text-faint text-[0.85rem]">No tracks known for this album yet.</div>
        ) : (
          album.tracks.map((track) => (
            <TrackRow key={track.id} track={track} albumId={album.id} multiDisc={multiDisc} />
          ))
        )}
      </div>
    </div>
  )
}
