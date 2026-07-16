import { useState } from 'react'
import { useDeleteTrack, useDownloadTrack } from '../api/hooks'
import { ConfirmDeleteModal } from './ConfirmDeleteModal'
import { Pill } from './Pill'

function formatDuration(seconds) {
  if (!seconds) return '—'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

function trackNumberLabel(track, multiDisc) {
  const n = track.track_number ? String(track.track_number).padStart(2, '0') : '--'
  if (multiDisc && track.disc_number) return `${track.disc_number}-${n}`
  return n
}

function TrackAction({ track, albumId }) {
  const mutation = useDownloadTrack()
  const [justQueued, setJustQueued] = useState(false)

  if (track.status === 'downloading') {
    return <Pill variant="downloading">Downloading…</Pill>
  }
  if (track.status === 'queued' || justQueued) {
    return <Pill variant="queued">Queued</Pill>
  }
  if (mutation.isPending) {
    return (
      <button disabled className="btn bg-panel-sunken border border-border text-text-dim">
        …
      </button>
    )
  }

  const label = track.status === 'error' ? 'Retry' : track.status === 'downloaded' ? 'Re-download' : 'Download'
  return (
    <button
      onClick={() =>
        mutation.mutate(
          { trackId: track.id, albumId },
          { onSuccess: () => setJustQueued(true) }
        )
      }
      className="btn bg-panel-sunken border border-border text-text hover:border-border-hi"
    >
      {label}
    </button>
  )
}

function DeleteTrackAction({ track, albumId }) {
  const [open, setOpen] = useState(false)
  const mutation = useDeleteTrack()

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        title="Delete track"
        aria-label="Delete track"
        className="text-text-faint hover:text-danger text-[0.85rem] px-1.5"
      >
        ✕
      </button>
      <ConfirmDeleteModal
        open={open}
        busy={mutation.isPending}
        title={`Delete “${track.title}”?`}
        description="This removes the track from your library. Choose whether to also delete the real audio file from disk — this cannot be undone."
        onCancel={() => setOpen(false)}
        onConfirm={(deleteFiles) =>
          mutation.mutate(
            { trackId: track.id, albumId, deleteFiles },
            { onSuccess: () => setOpen(false) }
          )
        }
      />
    </>
  )
}

export function TrackRow({ track, albumId, multiDisc }) {
  const noArtwork = track.status === 'downloaded' && track.has_artwork === false

  return (
    <div className="grid grid-cols-[48px_1fr_140px_100px_28px] items-center gap-4 px-5 py-3 border-b border-border last:border-b-0">
      <div className="font-mono text-[0.78rem] text-text-faint">{trackNumberLabel(track, multiDisc)}</div>
      <div className="min-w-0">
        <div className="text-[0.87rem] font-semibold truncate">{track.title}</div>
        {track.status === 'error' && track.error_message && (
          <div className="text-[0.76rem] text-danger mt-0.5 truncate" title={track.error_message}>
            {track.error_message}
          </div>
        )}
        {track.status === 'downloaded' && (
          <div className="text-[0.76rem] text-text-faint mt-0.5 flex items-center gap-1.5">
            {track.file_format?.toUpperCase()}
            {track.bitrate && ` · ${track.bitrate} kbps`}
            {noArtwork && <span className="text-mustard" title="No cover art embedded">· no artwork</span>}
          </div>
        )}
      </div>
      <div className="font-mono text-[0.8rem] text-text-dim">{formatDuration(track.duration_seconds)}</div>
      <div className="flex justify-end">
        <TrackAction track={track} albumId={albumId} />
      </div>
      <div className="flex justify-end">
        <DeleteTrackAction track={track} albumId={albumId} />
      </div>
    </div>
  )
}
