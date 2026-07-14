import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useSearch } from '../api/hooks'
import { TrackResultCard } from '../components/TrackResultCard'
import { AlbumResultCard } from '../components/AlbumResultCard'
import { ArtistResultCard } from '../components/ArtistResultCard'
import { PlaylistResultCard } from '../components/PlaylistResultCard'

const MODES = [
  { value: 'all', label: 'All' },
  { value: 'title', label: 'Title' },
  { value: 'album', label: 'Album' },
  { value: 'artist', label: 'Artist' },
]

function ResultSection({ title, count, children }) {
  return (
    <div className="mb-8">
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="font-display text-lg font-semibold">{title}</h2>
        {count && <span className="text-[0.75rem] text-text-faint">{count}</span>}
      </div>
      <div className="flex flex-col gap-3">{children}</div>
    </div>
  )
}

function Notice({ children, tone = 'faint' }) {
  const color = tone === 'error' ? 'text-danger' : 'text-text-faint'
  return <div className={`text-center ${color} text-[0.9rem] py-16`}>{children}</div>
}

function SearchResults({ data, query, mode }) {
  if (data.query_type === 'url') {
    const hasResult = data.tracks.length || data.albums.length || data.artists.length || data.playlist
    if (!hasResult) {
      return <Notice>Recognised the link, but couldn't resolve it. Double-check the URL and try again.</Notice>
    }
    return (
      <ResultSection title={`Found: ${data.url_type}`}>
        {data.tracks.map((t) => (
          <TrackResultCard key={t.musicbrainz_id || t.youtube_video_id} track={t} />
        ))}
        {data.albums.map((a) => (
          <AlbumResultCard key={a.musicbrainz_id || a.youtube_browse_id} album={a} />
        ))}
        {data.artists.map((a) => (
          <ArtistResultCard key={a.musicbrainz_id || a.youtube_channel_id} artist={a} />
        ))}
        {data.playlist && <PlaylistResultCard playlist={data.playlist} />}
      </ResultSection>
    )
  }

  const noResults = data.tracks.length === 0 && data.albums.length === 0 && data.artists.length === 0
  if (noResults) {
    return <Notice>No results for "{query}". Try a different spelling, or paste a YouTube Music link.</Notice>
  }

  return (
    <>
      {data.tracks.length > 0 && (
        <ResultSection title="Tracks" count={`${data.tracks.length} results`}>
          {data.tracks.map((t, i) => (
            <TrackResultCard key={t.musicbrainz_id || t.youtube_video_id || `${t.title}-${i}`} track={t} />
          ))}
        </ResultSection>
      )}
      {data.albums.length > 0 && (
        <ResultSection title="Albums" count={`${data.albums.length} results`}>
          {data.albums.map((a, i) => (
            <AlbumResultCard key={a.musicbrainz_id || a.youtube_browse_id || `${a.title}-${i}`} album={a} />
          ))}
        </ResultSection>
      )}
      {data.artists.length > 0 && (
        <ResultSection title="Artists" count={`${data.artists.length} results`}>
          {data.artists.map((a, i) => (
            <ArtistResultCard
              key={a.musicbrainz_id || a.youtube_channel_id || `${a.name}-${i}`}
              artist={a}
              linkToDetail={mode === 'artist'}
            />
          ))}
        </ResultSection>
      )}
    </>
  )
}

export default function Search() {
  const [params, setParams] = useSearchParams()
  const query = params.get('q') || ''
  const mode = params.get('mode') || 'all'
  const [input, setInput] = useState(query)
  const search = useSearch(query, mode)

  // Keep the input in sync when the query changes via the topbar search box.
  useEffect(() => {
    setInput(query)
  }, [query])

  function handleSubmit(event) {
    event.preventDefault()
    const q = input.trim()
    if (q) setParams({ q, mode })
  }

  function handleModeChange(nextMode) {
    if (query) setParams({ q: query, mode: nextMode })
    else setParams({ mode: nextMode })
  }

  return (
    <div>
      <form
        onSubmit={handleSubmit}
        className="flex items-center gap-3 bg-panel border border-border rounded-full px-5 py-3.5 mb-4 shadow-card dark:shadow-card-dark"
      >
        <span aria-hidden="true" className="text-lg">
          🔍
        </span>
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Search for a track, album, or artist — or paste a YouTube Music link…"
          className="bg-transparent outline-none text-text placeholder:text-text-faint text-[0.95rem] w-full"
          autoFocus
        />
        <button type="submit" className="btn btn-plum flex-shrink-0">
          Search
        </button>
      </form>

      <div className="flex items-center gap-2 mb-8">
        {MODES.map((m) => (
          <button
            key={m.value}
            type="button"
            onClick={() => handleModeChange(m.value)}
            className={`text-[0.82rem] font-medium px-3.5 py-1.5 rounded-full transition-colors ${
              mode === m.value
                ? 'text-plum bg-plum-tint font-semibold'
                : 'text-text-dim bg-panel-sunken border border-border hover:text-text'
            }`}
          >
            {m.label}
          </button>
        ))}
        {mode === 'artist' && (
          <span className="text-[0.75rem] text-text-faint ml-1">
            Searches MusicBrainz's artist index directly — click a result for their full discography.
          </span>
        )}
      </div>

      {!query && (
        <Notice>Search above to find tracks, albums, artists — or paste a YouTube Music link.</Notice>
      )}
      {query && search.isLoading && <Notice>Searching…</Notice>}
      {query && search.isError && <Notice tone="error">{search.error.message}</Notice>}
      {query && search.isSuccess && <SearchResults data={search.data} query={query} mode={mode} />}
    </div>
  )
}
