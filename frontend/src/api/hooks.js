import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export function useStats() {
  return useQuery({
    queryKey: ['stats'],
    queryFn: () => api.get('/api/stats'),
    refetchInterval: 15_000, // background safety net; SSE drives the live path
  })
}

export function useQueueByStatus(status, limit = 6) {
  return useQuery({
    queryKey: ['queue', status, limit],
    queryFn: () => api.get(`/api/queue?status=${status}&limit=${limit}`),
  })
}

/** The dashboard's "Active Queue" panel: active jobs first, then queued,
 * capped to `limit` total. Two small indexed queries, not one big scan. */
export function useActiveQueue(limit = 6) {
  const active = useQueueByStatus('active', limit)
  const queued = useQueueByStatus('queued', limit)
  const items = [...(active.data?.items ?? []), ...(queued.data?.items ?? [])].slice(0, limit)
  return {
    items,
    isLoading: active.isLoading || queued.isLoading,
    isError: active.isError || queued.isError,
  }
}

export function useActivity(limit = 6) {
  return useQuery({
    queryKey: ['activity', limit],
    queryFn: () => api.get(`/api/activity?limit=${limit}`),
  })
}

export function useIncompleteAlbums(limit = 6) {
  return useQuery({
    queryKey: ['albums', 'incomplete', limit],
    queryFn: () => api.get(`/api/library/albums?completeness=incomplete&limit=${limit}&sort=added`),
  })
}

export function useSearch(query) {
  return useQuery({
    queryKey: ['search', query],
    queryFn: () => api.get(`/api/search?q=${encodeURIComponent(query)}`),
    enabled: Boolean(query && query.trim()),
    retry: false,
    staleTime: 60_000,
  })
}

export function useAddToLibrary() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload) => api.post('/api/library/add', payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['stats'] })
      queryClient.invalidateQueries({ queryKey: ['queue'] })
      queryClient.invalidateQueries({ queryKey: ['albums'] })
    },
  })
}
