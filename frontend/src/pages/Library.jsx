import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useWindowVirtualizer } from '@tanstack/react-virtual'
import { useAlbumsInfinite } from '../api/hooks'
import { AlbumCard } from '../components/AlbumCard'
import { PlaylistsPanel } from '../components/PlaylistsPanel'

const COLUMNS = 5
const GAP = 18
const ROW_HEIGHT_ESTIMATE = 340 // px — tuned for a ~250px-wide card; corrected live via measureElement

const COMPLETENESS_OPTIONS = [
  { value: '', label: 'All completeness' },
  { value: 'complete', label: 'Complete' },
  { value: 'incomplete', label: 'Incomplete' },
  { value: 'empty', label: 'Empty' },
]
const FORMAT_OPTIONS = ['', 'mp3', 'flac', 'm4a', 'opus', 'wav', 'ogg']
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

export default function Library() {
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

  const rows = useMemo(() => {
    const chunked = []
    for (let i = 0; i < albums.length; i += COLUMNS) chunked.push(albums.slice(i, i + COLUMNS))
    return chunked
  }, [albums])

  const containerRef = useRef(null)
  const [scrollMargin, setScrollMargin] = useState(0)
  useLayoutEffect(() => {
    if (containerRef.current) setScrollMargin(containerRef.current.offsetTop)
  }, [rows.length === 0])

  const virtualizer = useWindowVirtualizer({
    count: hasNextPage ? rows.length + 1 : rows.length,
    estimateSize: () => ROW_HEIGHT_ESTIMATE,
    overscan: 3,
    gap: GAP,
    scrollMargin,
  })

  const virtualItems = virtualizer.getVirtualItems()

  useEffect(() => {
    const last = virtualItems[virtualItems.length - 1]
    if (!last) return
    if (last.index >= rows.length - 1 && hasNextPage && !isFetchingNextPage) {
      fetchNextPage()
    }
  }, [virtualItems, rows.length, hasNextPage, isFetchingNextPage, fetchNextPage])

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
          {FORMAT_OPTIONS.filter(Boolean).map((f) => (
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

      {isLoading ? (
        <div className="text-center text-text-faint text-[0.9rem] py-16">Loading…</div>
      ) : isError ? (
        <div className="text-center text-danger text-[0.9rem] py-16">Could not load the library.</div>
      ) : albums.length === 0 ? (
        <div className="bg-panel border border-border rounded-card px-6 py-16 text-center text-text-faint text-[0.9rem]">
          No albums match these filters.
        </div>
      ) : (
        <div ref={containerRef} style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
          {virtualItems.map((virtualRow) => {
            const row = rows[virtualRow.index]
            const style = {
              position: 'absolute',
              top: 0,
              left: 0,
              width: '100%',
              transform: `translateY(${virtualRow.start - scrollMargin}px)`,
            }
            if (!row) {
              return (
                <div
                  key={virtualRow.key}
                  ref={virtualizer.measureElement}
                  data-index={virtualRow.index}
                  style={style}
                  className="text-center text-text-faint text-[0.8rem] py-6"
                >
                  Loading more…
                </div>
              )
            }
            return (
              <div
                key={virtualRow.key}
                ref={virtualizer.measureElement}
                data-index={virtualRow.index}
                style={style}
                className="grid grid-cols-5 gap-[18px]"
              >
                {row.map((album) => (
                  <AlbumCard key={album.id} album={album} />
                ))}
              </div>
            )
          })}
        </div>
      )}

      <div className="mt-10">
        <PlaylistsPanel />
      </div>
    </div>
  )
}
