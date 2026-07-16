import { useState } from 'react'
import { useCompletePlaylist, useDeletePlaylist } from '../api/hooks'
import { ConfirmDeleteModal } from './ConfirmDeleteModal'
import { LibraryCard } from './LibraryCard'

function CompletePlaylistButton({ playlistId }) {
  const mutation = useCompletePlaylist()
  const [result, setResult] = useState(null)

  if (mutation.isPending) {
    return (
      <button disabled className="btn w-full bg-panel-sunken border border-border text-text-dim">
        Queuing…
      </button>
    )
  }
  if (result) {
    return (
      <button disabled className="btn w-full bg-sage-tint text-sage">
        {result.queued_jobs} queued ✓
      </button>
    )
  }
  return (
    <button
      onClick={(event) => {
        event.preventDefault() // card has no link, but keep clicks scoped to the button
        mutation.mutate(playlistId, { onSuccess: setResult })
      }}
      className="btn w-full btn-plum"
    >
      Complete this playlist
    </button>
  )
}

function m3uFileName(path) {
  if (!path) return null
  return path.split(/[\\/]/).pop()
}

function DeletePlaylistButton({ playlist }) {
  const [open, setOpen] = useState(false)
  const mutation = useDeletePlaylist()

  return (
    <>
      <button
        onClick={(event) => {
          event.preventDefault()
          setOpen(true)
        }}
        className="text-[0.72rem] text-text-faint hover:text-danger self-start"
      >
        Delete playlist
      </button>
      <ConfirmDeleteModal
        open={open}
        busy={mutation.isPending}
        title={`Delete “${playlist.name}”?`}
        description="This removes the playlist. Its tracks stay in your library untouched — they may belong to other playlists or albums. Choose whether to also delete the generated .m3u8 manifest file from disk."
        onCancel={() => setOpen(false)}
        onConfirm={(deleteFiles) =>
          mutation.mutate(
            { playlistId: playlist.id, deleteFiles },
            { onSuccess: () => setOpen(false) }
          )
        }
      />
    </>
  )
}

export function PlaylistCard({ playlist }) {
  const isComplete = playlist.completeness === 'complete'
  const manifestName = m3uFileName(playlist.m3u_path)

  return (
    <LibraryCard
      title={playlist.name}
      subtitle={`${playlist.total_tracks} track${playlist.total_tracks === 1 ? '' : 's'} · ${playlist.source}`}
      downloadedTracks={playlist.downloaded_tracks}
      expectedTracks={playlist.total_tracks}
      completeness={playlist.completeness}
      action={
        <div className="flex flex-col gap-2">
          {isComplete ? (
            <span className="text-[0.82rem] text-sage font-semibold">✓ Complete</span>
          ) : (
            <CompletePlaylistButton playlistId={playlist.id} />
          )}
          {manifestName && (
            <div
              className="text-[0.7rem] text-text-faint truncate font-mono"
              title={`Playlists/${manifestName} — regenerated as tracks finish downloading`}
            >
              📄 Playlists/{manifestName}
            </div>
          )}
          <DeletePlaylistButton playlist={playlist} />
        </div>
      }
    />
  )
}
