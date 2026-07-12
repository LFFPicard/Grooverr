import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

const ALBUMS_PAGE_SIZE = 60
const QUEUE_TAB_PAGE_SIZE = 20

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

function albumsQueryString({ search, completeness, format, sort }, extra = {}) {
  const params = new URLSearchParams()
  if (search) params.set('search', search)
  if (completeness) params.set('completeness', completeness)
  if (format) params.set('file_format', format)
  if (sort) params.set('sort', sort)
  for (const [key, value] of Object.entries(extra)) params.set(key, value)
  return params.toString()
}

/** Library grid data source (Section 9.4: virtualized + infinite-loaded so
 * rendering and fetching both stay cheap at a few thousand albums). */
export function useAlbumsInfinite(filters) {
  return useInfiniteQuery({
    queryKey: ['albums', 'list', filters],
    queryFn: ({ pageParam }) =>
      api.get(`/api/library/albums?${albumsQueryString(filters, { limit: ALBUMS_PAGE_SIZE, offset: pageParam })}`),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((sum, page) => sum + page.items.length, 0)
      return loaded < lastPage.total ? loaded : undefined
    },
  })
}

export function useAlbumDetail(albumId) {
  return useQuery({
    queryKey: ['albums', 'detail', albumId],
    queryFn: () => api.get(`/api/library/albums/${albumId}`),
    enabled: Boolean(albumId),
  })
}

export function usePlaylists(limit = 50) {
  return useQuery({
    queryKey: ['playlists', 'list', limit],
    queryFn: () => api.get(`/api/library/playlists?limit=${limit}`),
  })
}

export function useCompleteAlbum() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (albumId) => api.post(`/api/library/albums/${albumId}/complete`, {}),
    onSuccess: (_data, albumId) => {
      queryClient.invalidateQueries({ queryKey: ['albums', 'detail', albumId] })
      queryClient.invalidateQueries({ queryKey: ['albums', 'list'] })
      queryClient.invalidateQueries({ queryKey: ['albums', 'incomplete'] })
      queryClient.invalidateQueries({ queryKey: ['queue'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
    },
  })
}

export function useCompletePlaylist() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (playlistId) => api.post(`/api/library/playlists/${playlistId}/complete`, {}),
    onSuccess: (_data, playlistId) => {
      queryClient.invalidateQueries({ queryKey: ['playlists'] })
      queryClient.invalidateQueries({ queryKey: ['queue'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
    },
  })
}

export function useDownloadTrack() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ trackId }) => api.post(`/api/library/tracks/${trackId}/download`, {}),
    onSuccess: (_data, { albumId }) => {
      if (albumId) queryClient.invalidateQueries({ queryKey: ['albums', 'detail', albumId] })
      queryClient.invalidateQueries({ queryKey: ['queue'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
    },
  })
}

export function useQueueTab(jobType, status, page = 0) {
  const params = new URLSearchParams({ job_type: jobType, limit: QUEUE_TAB_PAGE_SIZE, offset: page * QUEUE_TAB_PAGE_SIZE })
  if (status) params.set('status', status)
  return useQuery({
    queryKey: ['queue', 'tab', jobType, status, page],
    queryFn: () => api.get(`/api/queue?${params.toString()}`),
  })
}

export function useRetryJob() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (jobId) => api.post(`/api/queue/${jobId}/retry`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['queue'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
    },
  })
}

export function useCancelJob() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (jobId) => api.del(`/api/queue/${jobId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['queue'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
    },
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
