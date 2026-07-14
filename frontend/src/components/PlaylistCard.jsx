import { useState } from 'react'
import { useCompletePlaylist } from '../api/hooks'
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
        </div>
      }
    />
  )
}
