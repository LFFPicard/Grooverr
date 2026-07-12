import { useState } from 'react'
import { usePlaylists, useCompletePlaylist } from '../api/hooks'
import { Panel } from './Panel'
import { Pill } from './Pill'

function CompletePlaylistButton({ playlistId, disabled }) {
  const mutation = useCompletePlaylist()
  const [result, setResult] = useState(null)

  if (disabled) {
    return (
      <button disabled className="btn bg-sage-tint text-sage">
        Complete
      </button>
    )
  }

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
    <button
      onClick={() => mutation.mutate(playlistId, { onSuccess: setResult })}
      className="btn btn-plum"
    >
      Complete this playlist
    </button>
  )
}

export function PlaylistsPanel() {
  const playlists = usePlaylists()

  if (playlists.isLoading) return null
  if (!playlists.data || playlists.data.items.length === 0) return null

  return (
    <Panel title="Playlists" tag={`${playlists.data.total} playlists`}>
      {playlists.data.items.map((playlist) => {
        const isComplete = playlist.completeness === 'complete'
        return (
          <div
            key={playlist.id}
            className="flex items-center gap-4 px-5 py-3.5 border-b border-border last:border-b-0"
          >
            <div className="w-11 h-11 rounded-lg bg-gradient-to-br from-plum-tint to-mustard-tint flex-shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="text-[0.9rem] font-semibold truncate">{playlist.name}</div>
              <div className="text-[0.78rem] text-text-faint mt-0.5">
                {playlist.downloaded_tracks} of {playlist.total_tracks} tracks
              </div>
            </div>
            {isComplete ? (
              <Pill variant="done">Complete</Pill>
            ) : (
              <CompletePlaylistButton playlistId={playlist.id} disabled={playlist.total_tracks === 0} />
            )}
          </div>
        )
      })}
    </Panel>
  )
}
