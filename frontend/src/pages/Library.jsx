import { useEffect, useMemo, useState } from 'react'
import { useAlbumsInfinite, usePlaylistsInfinite } from '../api/hooks'
import { AlbumCard } from '../components/AlbumCard'
import { PlaylistCard } from '../components/PlaylistCard'
import { VirtualizedCardGrid } from '../components/VirtualizedCardGrid'

const TABS = [
  { key: 'albums', label: 'Albums' },
  { key: 'playlists', label: 'Playlists' },
]

const COMPLETENESS_OPTIONS = [
  { value: '', label: 'All completeness' },
  { value: 'complete', label: 'Complete' },
  { value: 'incomplete', label: 'Incomplete' },
  { value: 'empty', label: 'Empty' },
]
const FORMAT_OPTIONS = ['mp3', 'flac', 'm4a', 'opus', 'wav', 'ogg']
const SORT_OPTIONS = [
  { value: 'title', label: 'Title' },
  { value: 'artist', label: 'Artist' },
  { value: 'year', label: 'Year' },
  { value: 'added', label: 'Recently added' },
]

function useDebouncedValue(value, delay = 300) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}

const selectClass =
  'bg-panel-sunken border border-border rounded-full px-3.5 py-2 text-[0.82rem] text-text outline-none'

function AlbumsTab() {
  const [searchInput, setSearchInput] = useState('')
  const [completeness, setCompleteness] = useState('')
  const [format, setFormat] = useState('')
  const [sort, setSort] = useState('title')
  const search = useDebouncedValue(searchInput, 300)

  const filters = useMemo(
    () => ({ search: search || undefined, completeness: completeness || undefined, format: format || undefined, sort }),
    [search, completeness, format, sort]
  )

  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading, isError } = useAlbumsInfinite(filters)
  const albums = useMemo(() => data?.pages.flatMap((page) => page.items) ?? [], [data])
  const total = data?.pages[0]?.total

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 mb-6">
        <input
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
          placeholder="Filter by album or artist…"
          className="bg-panel-sunken border border-border rounded-full px-4 py-2 text-[0.85rem] text-text placeholder:text-text-faint outline-none w-64"
        />
        <select value={completeness} onChange={(e) => setCompleteness(e.target.value)} className={selectClass}>
          {COMPLETENESS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <select value={format} onChange={(e) => setFormat(e.target.value)} className={selectClass}>
          <option value="">All formats</option>
          {FORMAT_OPTIONS.map((f) => (
            <option key={f} value={f}>
              {f.toUpperCase()}
            </option>
          ))}
        </select>
        <select value={sort} onChange={(e) => setSort(e.target.value)} className={selectClass}>
          {SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              Sort: {o.label}
            </option>
          ))}
        </select>
        {typeof total === 'number' && (
          <span className="text-[0.8rem] text-text-faint ml-auto font-mono">{total} albums</span>
        )}
      </div>

      <VirtualizedCardGrid
        items={albums}
        isLoading={isLoading}
        isError={isError}
        hasNextPage={hasNextPage}
        isFetchingNextPage={isFetchingNextPage}
        fetchNextPage={fetchNextPage}
        renderCard={(album) => <AlbumCard key={album.id} album={album} />}
        emptyMessage="No albums match these filters."
        errorMessage="Could not load the library."
      />
    </div>
  )
}

function PlaylistsTab() {
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading, isError } = usePlaylistsInfinite()
  const playlists = useMemo(() => data?.pages.flatMap((page) => page.items) ?? [], [data])
  const total = data?.pages[0]?.total

  return (
    <div>
      {typeof total === 'number' && total > 0 && (
        <div className="flex items-center mb-6">
          <span className="text-[0.8rem] text-text-faint ml-auto font-mono">{total} playlists</span>
        </div>
      )}
      <VirtualizedCardGrid
        items={playlists}
        isLoading={isLoading}
        isError={isError}
        hasNextPage={hasNextPage}
        isFetchingNextPage={isFetchingNextPage}
        fetchNextPage={fetchNextPage}
        renderCard={(playlist) => <PlaylistCard key={playlist.id} playlist={playlist} />}
        emptyMessage="No playlists yet — paste a YouTube Music playlist link in Search to add one."
        errorMessage="Could not load playlists."
      />
    </div>
  )
}

export default function Library() {
  const [tab, setTab] = useState('albums')

  return (
    <div>
      <div className="flex items-center gap-2 mb-6">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`text-[0.85rem] font-medium px-4 py-2 rounded-full transition-colors ${
              tab === t.key
                ? 'text-plum bg-plum-tint font-semibold'
                : 'text-text-dim bg-panel-sunken border border-border hover:text-text'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'albums' ? <AlbumsTab /> : <PlaylistsTab />}
    </div>
  )
}
