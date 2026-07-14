import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useWindowVirtualizer } from '@tanstack/react-virtual'

const COLUMNS = 5
const GAP = 18
const ROW_HEIGHT_ESTIMATE = 340 // px — tuned for a ~250px-wide card; corrected live via measureElement

/**
 * Windowed card grid (Section 9.4) shared by the Library screen's Albums
 * and Playlists tabs — only ever renders the rows in/near the viewport
 * regardless of how many items are loaded, and pulls the next page as the
 * user scrolls near the end. Both tabs get identical scroll performance
 * and completeness-badge treatment by construction, since they render
 * through this one component (Section 8, decision resolved 2026-07-13).
 */
export function VirtualizedCardGrid({
  items,
  isLoading,
  isError,
  hasNextPage,
  isFetchingNextPage,
  fetchNextPage,
  renderCard,
  emptyMessage,
  errorMessage = 'Could not load this list.',
}) {
  const rows = useMemo(() => {
    const chunked = []
    for (let i = 0; i < items.length; i += COLUMNS) chunked.push(items.slice(i, i + COLUMNS))
    return chunked
  }, [items])

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

  if (isLoading) {
    return <div className="text-center text-text-faint text-[0.9rem] py-16">Loading…</div>
  }
  if (isError) {
    return <div className="text-center text-danger text-[0.9rem] py-16">{errorMessage}</div>
  }
  if (items.length === 0) {
    return (
      <div className="bg-panel border border-border rounded-card px-6 py-16 text-center text-text-faint text-[0.9rem]">
        {emptyMessage}
      </div>
    )
  }

  return (
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
            {row.map(renderCard)}
          </div>
        )
      })}
    </div>
  )
}
