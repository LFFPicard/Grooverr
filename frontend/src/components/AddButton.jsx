import { useState } from 'react'
import { useAddToLibrary } from '../api/hooks'

/**
 * Add-to-library button used by every search result card. Immediate visual
 * feedback per Section 8's non-negotiable UX requirement: pending/success/
 * error states render instantly from local mutation state, no waiting on a
 * full refetch.
 */
export function AddButton({ payload, label = 'Add to library' }) {
  const mutation = useAddToLibrary()
  const [result, setResult] = useState(null)

  function handleClick() {
    setResult(null)
    mutation.mutate(payload, { onSuccess: setResult })
  }

  if (mutation.isPending) {
    return (
      <button disabled className="btn bg-panel-sunken border border-border text-text-dim">
        Adding…
      </button>
    )
  }

  if (result) {
    const addedSomething = result.added_track_ids?.length > 0 || result.added_album_id || result.added_artist_id
    if (addedSomething && result.queued_jobs > 0) {
      return (
        <button disabled className="btn bg-sage-tint text-sage">
          Added ✓ · {result.queued_jobs} queued
        </button>
      )
    }
    if (addedSomething) {
      return (
        <button disabled className="btn bg-sage-tint text-sage">
          Added ✓
        </button>
      )
    }
    return (
      <button disabled className="btn bg-panel-sunken border border-border text-text-dim">
        Already in library
      </button>
    )
  }

  if (mutation.isError) {
    return (
      <button onClick={handleClick} title={mutation.error.message} className="btn bg-danger-tint text-danger">
        Failed — retry
      </button>
    )
  }

  return (
    <button onClick={handleClick} className="btn btn-plum flex-shrink-0">
      {label}
    </button>
  )
}
