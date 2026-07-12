import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'

const THROTTLE_MS = 400

/**
 * Subscribes to /api/queue/events (SSE) for the lifetime of the component
 * and invalidates the relevant TanStack Query caches on change, so the
 * Dashboard's queue panel updates live (Batch 6 DoD) without polling.
 *
 * Progress ticks arrive rapidly during a fast download (observed live:
 * 1/2/4/8/17/35/71/84% within ~1s) — invalidating ['queue'] on every single
 * tick would hammer the API, so queue invalidation is throttled. Stats and
 * activity only change on a job's terminal transition, so those invalidate
 * immediately and unthrottled on done/error/cancelled.
 */
export function useQueueEvents() {
  const queryClient = useQueryClient()
  const throttleTimer = useRef(null)

  useEffect(() => {
    const source = new EventSource('/api/queue/events')

    const invalidateQueueThrottled = () => {
      if (throttleTimer.current) return
      throttleTimer.current = setTimeout(() => {
        throttleTimer.current = null
        queryClient.invalidateQueries({ queryKey: ['queue'] })
      }, THROTTLE_MS)
    }

    source.onmessage = (event) => {
      let payload
      try {
        payload = JSON.parse(event.data)
      } catch {
        return
      }
      invalidateQueueThrottled()
      const status = payload?.job?.status
      if (status === 'done' || status === 'error' || status === 'cancelled') {
        queryClient.invalidateQueries({ queryKey: ['stats'] })
        queryClient.invalidateQueries({ queryKey: ['activity'] })
        queryClient.invalidateQueries({ queryKey: ['albums'] })
        queryClient.invalidateQueries({ queryKey: ['playlists'] })
      }
    }

    // EventSource retries automatically on its own; nothing to do on error
    // beyond letting the browser reconnect.

    return () => {
      source.close()
      if (throttleTimer.current) clearTimeout(throttleTimer.current)
    }
  }, [queryClient])
}
