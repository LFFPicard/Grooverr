# Grooverr — Build Specification

**Status:** Ready for implementation
**Audience:** This document is written to be handed directly to an AI coding agent (Claude Code / Fable) as the source of truth for the build. It is intentionally explicit about architecture decisions so the agent does not need to guess or improvise on anything load-bearing.
**Owner:** Gary Thwaites
**Repo (planned):** `github.com/LFFPicard/Grooverr`

---

## 0. How to use this document

This build is split into **sequential batches** (Section 10). Each batch is scoped to be completable and testable in a single agent session without running into usage limits. **Do not start a batch until the previous one is confirmed working.** Each batch ends with a "Definition of Done" checklist — treat that as a hard gate.

When starting a new session/batch with the coding agent, paste in:
1. This document (or the relevant sections)
2. The batch number you're starting
3. Confirmation of what was completed in the prior batch (or point it at the repo state)

---

## 1. Vision

Grooverr is a self-hosted music acquisition and library manager. The workflow is:

1. **Search** — for a track, album, artist, or paste a YouTube Music playlist link (same interaction model as Overseerr/Ombi searching for movies/TV)
2. **Resolve** — Grooverr finds canonical metadata (via MusicBrainz primarily) and locates the best-matching audio source (YouTube Music)
3. **Download** — audio is fetched, tagged, and named to a strict, predictable convention (MusicBrainz Picard-compatible)
4. **Organize** — files land in a folder structure that Plex, Navidrome, Jellyfin, or any scraper can read without further massaging
5. **Track** — a library view shows what's downloaded, what's incomplete (e.g. an album missing 3 of 12 tracks), what's queued, and what's actively downloading — modeled on Lidarr's UX

The end state: drop in an artist, album, track, or playlist link, and Grooverr produces a correctly tagged, correctly organized, offline media library — with zero manual file renaming or tag editing ever required.

---

## 2. Branding

| | |
|---|---|
| **Name** | Grooverr |
| **Tagline (working)** | "Point it at the music. Get a library." |
| **Visual identity** | See Section 8 (UI/UX spec) — "Sleeve Catalog" token system: warm off-white / deep plum / mustard, serif display type, card-based layout with soft shadows |
| **Logo direction** | A tonearm/stylus over a groove-ring mark. Simple enough to read at 32×32 favicon size and as an Unraid CA store icon. (Not yet finalized — treat as a placeholder square icon with a "G" monogram in plum until real logo is supplied.) |
| **Standalone product** | Grooverr is NOT branded as part of the Atrium ecosystem. It may later expose a small status widget Atrium can embed, but it ships and is documented as an independent self-hosted app, same relationship Lidarr has to Organizr. |

---

## 3. Goals and non-goals

### Goals
- Search and resolve music by track, album, artist, or playlist (YouTube Music links, or free-text search)
- Download audio at a **user-configurable quality ceiling** per download (not a fixed global setting)
- Tag files using **MusicBrainz as the primary metadata source**, falling back to YouTube Music data if MusicBrainz has no match
- Output files in a MusicBrainz Picard-compatible naming/folder convention (Section 6)
- A library browser showing completeness per album (X of Y tracks), with one-click "complete this album" to queue the missing tracks
- A live queue view: metadata resolution queue + download queue, separately visible
- Single-user, no auth complexity required (local network / reverse-proxied by the user's own auth layer if they want one)
- Fast at scale: must stay responsive with a library in the thousands of tracks (Section 9 — non-negotiable performance requirements)
- Docker-first, Unraid Community Applications template included

### Non-goals (explicitly out of scope for v1)
- Multi-user accounts or permissions
- Mobile app (responsive web UI is sufficient)
- Built-in music player (this is a library *acquisition and organization* tool, playback is Plex/Navidrome/Jellyfin's job)
- Automatic "watch this artist for new releases" (may be a v2 feature — flagged in backlog, not built now). **Decision (resolved 2026-07-12):** for v1, "add artist" from search creates the `Artist` row only — it does not pull or queue their discography. Full Lidarr-style discography monitoring is a v2 feature, deliberately deferred.
- Lyrics embedding (may be added later, not a v1 requirement)
- Any Spotify integration whatsoever. Spotify required a Premium developer account, hit API app-creation limits, and returned inconsistently-shaped data during the spotDL-GUI build — not worth the dependency for a "download music you already have the right to" tool. **MusicBrainz + YouTube Music cover the full feature set**, including playlist import (via YouTube Music links).

---

## 4. Tech stack

| Layer | Choice | Why |
|---|---|---|
| **Backend language** | Python 3.12 | Matches existing skillset, mature ecosystem for the exact libraries needed (mutagen, musicbrainzngs, ytmusicapi, yt-dlp) |
| **Backend framework** | FastAPI | Async-native, fast, automatic OpenAPI docs, plays well with background task workers |
| **Database** | SQLite, **WAL mode mandatory** | Simplicity of a single-file DB, but WAL mode allows concurrent reads while background workers write — critical so browsing the library never blocks on an active download. See Section 9. |
| **ORM** | SQLModel (or SQLAlchemy 2.0 core) | Type-safe, integrates cleanly with FastAPI's Pydantic models |
| **Background task/queue** | Native `asyncio` task workers with a persisted job table (no Redis/Celery) | Per user preference — keep the stack to a single container. Job state is persisted to SQLite so a container restart doesn't lose queue state (Section 9.3). |
| **Metadata — primary** | MusicBrainz API (`musicbrainzngs` or direct REST) | Most accurate canonical tagging data, per user preference. No API key required. |
| **Metadata — fallback + playlists** | YouTube Music (`ytmusicapi`) | Used if MusicBrainz has no match for a given search, and as the source for playlist link resolution |
| **Audio search/resolution** | `ytmusicapi` for matching, `yt-dlp` for the actual audio fetch | YouTube Music is the sole audio and playlist source. No Spotify dependency anywhere in the stack. |
| **Tagging** | `mutagen` | Writes ID3/Vorbis/MP4 tags depending on output format, handles embedded album art |
| **Frontend framework** | React + Vite | Fast dev/build, matches existing frontend experience |
| **Styling** | Tailwind CSS, custom design tokens (Section 8) | Utility-first, fast to build the specific "Sleeve Catalog" look without fighting a component library's opinions |
| **Data fetching** | TanStack Query | Caching, background refetch, works well with the polling/SSE pattern used for live queue updates |
| **Live queue updates** | Server-Sent Events (SSE) | Simpler than WebSockets for one-directional "queue state changed" pushes, lower overhead, easier to reason about with FastAPI |
| **Containerization** | Single Docker image, multi-stage build (Python backend serves built React static files) | One container to deploy, matches the pattern already used for the spotDL-GUI Unraid app |
| **CI/CD** | GitHub Actions → Docker Hub, same pattern as the spotDL-GUI repo | Already proven to work |

---

## 5. Data model

Core entities (exact field lists are a starting point, the agent may extend as needed but should not remove or rename without flagging it):

```
Artist
  id (uuid, pk)
  name
  musicbrainz_id (nullable)
  spotify_id (nullable)
  sort_name
  created_at

Album
  id (uuid, pk)
  artist_id (fk -> Artist)
  title
  musicbrainz_id (nullable)
  spotify_id (nullable)
  release_year
  album_type (album | single | compilation | ep)
  total_tracks          -- expected count, from metadata source
  cover_art_url
  created_at

Track
  id (uuid, pk)
  album_id (fk -> Album)
  title
  track_number
  disc_number
  duration_seconds
  musicbrainz_id (nullable)
  spotify_id (nullable)
  file_path (nullable — null until downloaded)
  file_format (mp3 | flac | m4a | opus | wav | ogg, nullable until downloaded)
  bitrate (nullable until downloaded)
  status (missing | queued | downloading | downloaded | error)
  audio_source (youtube-music | youtube, nullable until downloaded)
  audio_source_url (nullable)
  error_message (nullable)
  created_at
  downloaded_at (nullable)

QueueItem
  id (uuid, pk)
  track_id (fk -> Track, nullable — null for "resolve metadata" jobs not yet tied to a track)
  job_type (metadata_resolve | download)
  status (queued | active | done | error)
  progress_percent (0-100)
  priority (int, lower = higher priority)
  requested_quality (user-configurable ceiling for this specific job)
  created_at
  started_at (nullable)
  finished_at (nullable)
  error_message (nullable)

Settings
  key (pk)
  value (json)
  -- e.g. default_quality_ceiling, musicbrainz_rate_limit, output_path_template, etc.

Playlist
  id (uuid, pk)
  name
  source (youtube-music)
  source_url
  source_playlist_id
  created_at

PlaylistTrack
  id (uuid, pk)
  playlist_id (fk -> Playlist)
  track_id (fk -> Track)
  position (int)     -- track order within the playlist
```

**Decision (resolved 2026-07-12):** Playlist/PlaylistTrack tables are added per the above — additive migration, no changes to existing tables required. This is what "Complete this playlist" (Section 7.4) groups against; without it there's nothing to track playlist membership by once tracks are enqueued individually.

**Indexes required (non-negotiable, see Section 9):**
- `Track.album_id`, `Track.status`
- `Album.artist_id`
- `QueueItem.status`, `QueueItem.job_type`
- Composite index on `(Album.artist_id, Album.title)` for library search
- `PlaylistTrack.playlist_id`, `PlaylistTrack.track_id`

---

## 6. File naming & folder convention

Must match MusicBrainz Picard's default and most common convention, so any external scraper (Plex, Navidrome, Jellyfin, Lidarr-adjacent tooling) reads it correctly without configuration:

```
{MusicRoot}/{AlbumArtist}/{Album} ({ReleaseYear})/{DiscNumber-}{TrackNumber} - {Title}.{ext}
```

Examples:
```
/music/Daft Punk/Random Access Memories (2013)/01 - Give Life Back to Music.flac
/music/Arcade Fire/Reflektor (2013)/1-01 - Reflektor.mp3
/music/Arcade Fire/Reflektor (2013)/2-03 - Supersymmetry.mp3
```

Rules:
- `DiscNumber-` prefix on the track number **only appears if the album has more than one disc**
- Track number always zero-padded to 2 digits
- Illegal filesystem characters (`/ \ : * ? " < > |`) stripped or replaced with `-`
- This template must be **user-configurable in Settings** (stored as a Jinja-style template string), but the above is the default and what ships out of the box
- Embedded cover art is **attempted on every file** (pulled from the metadata source, highest resolution available). **Decision (resolved 2026-07-12):** if no art is available (e.g. Cover Art Archive has no image for a release), the download proceeds without it — logged as a warning, not a failure. A track with correct audio and tags but no artwork is a better outcome than a failed download; Picard itself doesn't fail on missing art either. Missing-art tracks should be visually flagged in the Library UI (Batch 7) so the user can spot and manually fix them if they care to, but this never blocks the pipeline.
- ID3/Vorbis tags written: title, artist, album artist, album, track number, disc number, year, genre (if available), MusicBrainz track/release/artist IDs (as custom tags — this is what makes it Picard-compatible for future re-tagging)

---

## 7. Core workflows

### 7.1 Search & Add
1. User types a free-text query, or pastes a YouTube Music URL, into the search bar
2. If it's a URL: detect type (track/album/artist/playlist) and resolve directly
3. If it's free text: query MusicBrainz first; if no confident match, fall back to YouTube Music search
4. Results shown as cards (track/album/artist/playlist), user picks one or more to add
5. Adding creates `Album`/`Track` rows with `status=missing`, and enqueues a `metadata_resolve` job per track (or per album, resolving all child tracks in one pass where the source supports it)

### 7.2 Metadata resolution pipeline
1. Worker picks up a `metadata_resolve` QueueItem
2. Query MusicBrainz for canonical release/track data using best available identifiers (ISRC if we have it, else artist+title+album fuzzy match)
3. If no MusicBrainz match found, fall back to YouTube Music metadata
4. Populate/patch the `Track`/`Album`/`Artist` rows with whatever was found
5. Enqueue a `download` QueueItem for the track

### 7.3 Download pipeline
1. Worker picks up a `download` QueueItem
2. Search YouTube Music (`ytmusicapi`) for a best match using title + artist + duration (duration matching within a few seconds tolerance is the primary anti-mismatch signal)
3. If no confident YouTube Music match, fall back to a plain YouTube search via the same matching logic
4. `yt-dlp` fetches the audio at the job's `requested_quality`
5. Post-process: convert to target format if needed, embed tags via `mutagen`, write to the path per Section 6
6. Update `Track.status = downloaded`, set `file_path`, `bitrate`, `audio_source`
7. On any failure at any step: `Track.status = error`, `error_message` populated, **do not silently drop the job** — it must be visible in the UI queue as an error state the user can retry

### 7.4 Library completeness tracking
- Every album's card in the Library view shows `X of Y tracks` — `Y` comes from the metadata source's `total_tracks`, `X` is a live count of `Track.status = downloaded` for that album
- "Complete this album" button enqueues `download` jobs for every track in that album currently `status != downloaded`
- Same pattern for a playlist: "Complete this playlist" queues everything not yet downloaded

### 7.5 Queue system
- Two visually distinct sub-queues in the UI: **Resolving** (metadata jobs) and **Downloading** (audio fetch jobs) — mirrors the dashboard mockup's "Active Queue" panel
- Each item shows live progress (SSE-pushed), with retry/cancel actions per item
- Queue persists across container restarts (it's just rows in SQLite with `status=queued`/`active` — on startup, any job stuck in `active` from an unclean shutdown gets reset to `queued`)

---

## 8. UI/UX specification

**Direction confirmed: "Sleeve Catalog"** — light-first (with dark mode available via toggle), warm off-white background, plum primary accent, mustard secondary accent, serif display type for titles, sans for UI chrome/data. Raised cards with soft shadows, generous border-radius, no harsh borders.

### Design tokens (confirmed, carry forward exactly)

```css
--bg: #F6F5F2;
--panel: #FFFFFF;
--panel-sunken: #EFEDE8;
--border: #E2DFD7;
--border-hi: #CFCABC;
--plum: #4B3F72;
--plum-tint: #EAE7F4;
--mustard: #C98A2C;
--mustard-tint: #F6E9D2;
--sage: #5C8368;        /* success / complete state */
--sage-tint: #E4EDE6;
--red: #B5493D;          /* error state */
--red-tint: #F5E3E0;
--text: #262320;
--text-dim: #6B665C;
--text-faint: #A39D8F;

font-display: 'Fraunces', serif;   /* titles, album/artist names */
font-body: 'Inter', sans-serif;    /* UI chrome, labels, buttons */
font-mono: 'IBM Plex Mono', monospace;  /* data — track counts, durations, percentages */
```

Dark mode variant (toggle, not default) — see the reference mockup for exact dark token values.

### Screens required

1. **Dashboard** — stat row (downloading / queued / library size / incomplete albums), active queue panel, recent activity feed, "incomplete albums" grid teaser. *(Reference: `/design/dashboard-reference.html` in the repo — this is the confirmed Sleeve Catalog mockup, use it as the literal starting point, do not redesign from scratch. It's a static standalone HTML file with inline CSS; treat its layout, spacing, and component structure as canonical, and port it into the actual React component structure rather than reinventing it.)*
2. **Search** — search bar (same as dashboard's, or a dedicated larger version), result cards for tracks/albums/artists/playlists, "Add to library" action per result
3. **Library** — full browsable grid of all albums, filterable by artist / completeness status / format, each card shows the completion badge pattern from the dashboard mockup. Clicking an album opens an **Album Detail** view listing every track with its individual status (downloaded / missing / queued / error) and a per-track "download this one" action
4. **Queue** — full queue view (not just the dashboard teaser), split into Resolving / Downloading tabs, with retry/cancel per item
5. **Settings** — API credentials (MusicBrainz doesn't need a key but rate-limits by user-agent string; optional YouTube cookie file upload exactly like the spotDL-GUI pattern already proven), default quality ceiling, output path template editor, theme toggle

### Non-negotiable UX requirements
- Every async action (add to library, retry, cancel, complete album) gives immediate visual feedback — optimistic UI update, don't wait for a full refetch
- Empty states are informative, not blank ("No downloads queued — search above to add music" rather than an empty panel)
- Error states are specific ("No YouTube Music match found for this track" rather than a generic "Error")

---

## 9. Performance requirements (non-negotiable)

This section exists because a Lidarr-comparable tool needs to stay fast with a large library, and that has to be designed in from the start, not retrofitted.

### 9.1 Database
- SQLite **must** run in WAL mode (`PRAGMA journal_mode=WAL;`) — set this on every connection at startup. This is what allows the library UI to keep reading smoothly while background workers are writing queue/download progress.
- Required indexes are listed in Section 5 — create them in the initial migration, not as an afterthought.
- `PRAGMA synchronous=NORMAL` (safe in WAL mode, meaningfully faster than the default `FULL`).

### 9.2 API layer
- Library and queue list endpoints **must** be paginated (`limit`/`offset` or cursor-based) and support server-side filtering (by artist, completeness, status). Never return the entire library in one response.
- Album detail (single album + its tracks) is a separate, cheap endpoint — the library grid endpoint should return summary data only (cover art URL, title, artist, X/Y completeness), not full track lists.

### 9.3 Background workers
- Workers run as `asyncio` tasks within the same FastAPI process, pulling from the `QueueItem` table (poll or use `asyncio.Event` signaling on enqueue — agent's choice, but must not busy-loop hammering the DB).
- Configurable concurrency limit (default: 3 concurrent downloads) so the container doesn't saturate the host's bandwidth or CPU on ffmpeg conversions.
- Job state written to SQLite on every meaningful progress update so a restart mid-download resumes cleanly (job goes back to `queued`, not lost).

### 9.4 Frontend
- Library grid **must** use virtualized/windowed rendering (e.g. `@tanstack/react-virtual`) once the library exceeds ~100 items — only render what's in viewport. This is the single biggest lever for staying smooth at a few thousand albums.
- Cover art images lazy-loaded (`loading="lazy"`) and served through a thumbnail-sized endpoint, not the full-resolution source image, for grid views.
- TanStack Query cache configured with sensible `staleTime` so switching between Dashboard/Library/Queue tabs doesn't refetch everything every time.

### 9.5 Target benchmarks (for the agent to self-verify against during Batch 6/7 testing)
- Library grid with 2,000 albums: initial render < 1s, scroll stays at 60fps
- Adding a new album to the queue: UI reflects the change in < 200ms (optimistic update, before the network round-trip even completes)
- Dashboard stat row: single aggregate query, not N+1 queries per stat

---

## 10. Build batches (execution plan)

Each batch below is scoped to be a self-contained agent session. **Confirm the "Definition of Done" for a batch before moving to the next.**

---

### Batch 1 — Project scaffolding
**Scope:**
- Repo structure: `/backend` (FastAPI), `/frontend` (React+Vite), root `Dockerfile`, `docker-compose.yml`
- FastAPI app boots, serves a health-check endpoint (`GET /api/health`)
- SQLite DB initializes with WAL mode + the full schema from Section 5 as an initial migration (use Alembic or a simple versioned SQL migration approach — agent's choice)
- React app boots via Vite, Tailwind configured with the exact design tokens from Section 8 as CSS variables
- Docker build produces one image that serves the built frontend as static files from the FastAPI app

**Definition of done:**
- `docker build` succeeds
- Container runs, `/api/health` returns 200
- Visiting the container's port in a browser shows a blank React app styled with the correct background/font tokens (even if no real screens exist yet)

---

### Batch 2 — Metadata resolution engine
**Scope:**
- MusicBrainz client wrapper (search by artist/title/album, fetch release+recording data, respect their rate limit with a proper user-agent string)
- YouTube Music client wrapper (`ytmusicapi` — search + playlist resolution, no downloading yet)
- The fallback chain logic from Section 7.2: MusicBrainz → YouTube Music
- All fields pulled from external API responses **must** use safe `.get()` access with defaults, never direct dict indexing (`data["field"]`) — this is a direct lesson from the spotDL-GUI build, where unsafe indexing caused repeated KeyError crashes as the Spotify API's response shape changed under us. Do not repeat that pattern here.
- Unit-testable as a standalone module (no UI needed yet) — a CLI script or test suite that takes a query and prints resolved metadata is sufficient to verify this batch

**Definition of done:**
- Given a track title + artist, the resolver returns canonical metadata with MusicBrainz ID when available, correct fallback when it's not
- Given a YouTube Music track, album, artist, or playlist URL, the resolver detects the type and resolves correctly
- No unsafe dict indexing anywhere in the resolver code — verified by review, not just by it happening to work on today's API responses

---

### Batch 3 — Download & tagging engine
**Scope:**
- `yt-dlp` wrapper: given a YouTube Music search result, downloads audio at a specified quality
- Format conversion (ffmpeg) to the target output format
- `mutagen` tagging: writes all required tags + embedded cover art per Section 6
- File placement logic implementing the naming/folder convention from Section 6, including the disc-number-prefix conditional rule
- Standalone testable: given resolved metadata + a YouTube Music match, produces a correctly named, correctly tagged file on disk

**Definition of done:**
- A single track, given metadata + source, downloads and lands at the exact expected path with correct tags (verify by inspecting the file's tags directly)
- Multi-disc album case tested (disc prefix appears correctly)
- Illegal filename characters handled correctly

---

### Batch 4 — Queue system & background workers
**Scope:**
- `QueueItem` CRUD + the async worker pool from Section 9.3
- Wires Batch 2 (resolution) and Batch 3 (download) into the queue pipeline described in Section 7.2/7.3
- SSE endpoint pushing live queue state changes
- Startup recovery logic (stuck `active` jobs reset to `queued` on boot)
- Configurable concurrency limit in Settings

**Definition of done:**
- Enqueuing a track by title+artist results in it being resolved, downloaded, tagged, and placed on disk with zero manual intervention
- Killing the container mid-download and restarting it correctly resumes/retries rather than losing the job
- SSE stream correctly reflects real-time progress

---

### Batch 5 — Core API layer
**Scope:**
- REST endpoints for: search, add-to-library, library listing (paginated, per Section 9.2), album detail, artist listing, queue listing, retry/cancel actions, settings CRUD
- All endpoints match the performance requirements in Section 9.2 (pagination, no N+1 queries — use `EXPLAIN QUERY PLAN` to sanity check the heavier ones)

**Definition of done:**
- Full OpenAPI docs (`/docs`) show every endpoint with correct request/response schemas
- Library endpoint tested with a seeded 1,000+ row dataset to confirm pagination and index usage actually work (not just correct on a 5-row dev dataset)

---

### Batch 6 — Frontend: Dashboard + Search
**Scope:**
- Dashboard screen exactly per the confirmed mockup (Style B / Sleeve Catalog) — stat row, active queue panel, recent activity, incomplete albums teaser
- Search screen — search bar, result cards, add-to-library flow
- SSE integration so the dashboard queue panel updates live
- Light/dark toggle wired up and persisted (localStorage or a settings row)

**Definition of done:**
- Visually matches the confirmed mockup
- Searching and adding a track actually triggers the full pipeline end-to-end (this is the first batch where the whole system is used together)

---

### Batch 7 — Frontend: Library + Album Detail + Queue
**Scope:**
- Library grid with virtualization (Section 9.4) — must be tested against a seeded large dataset, not just a handful of albums
- Album Detail view (per-track status list, individual retry/download actions)
- Full Queue screen (Resolving/Downloading tabs, retry/cancel)
- "Complete this album" / "Complete this playlist" actions

**Definition of done:**
- Library screen tested against 1,000+ seeded albums, scroll performance verified against the Section 9.5 benchmarks
- Album completeness badges are accurate and update live as tracks finish downloading

---

### Batch 8 — Settings screen + credential handling
**Scope:**
- Settings UI: MusicBrainz user-agent config, YouTube cookie file upload (reuse the exact drag-and-drop pattern already proven working in spotDL-GUI — use a `<label for=>` wrapping the hidden file input, not an `onclick` handler, per the lesson learned there), default quality ceiling, output path template editor with live preview
- Credentials stored in `/config` volume, never in the music output volume (same security pattern as spotDL-GUI)

**Definition of done:**
- Settings persist across container restarts
- Cookie file upload works correctly in Chrome, Firefox, and Edge (this bit specifically bit us before — verify in all three)

---

### Batch 9 — Packaging & Unraid template
**Scope:**
- Final Dockerfile hardening (multi-stage build, minimal final image size)
- `docker-compose.yml`
- Unraid Community Applications XML template (`/config` and `/music` volumes, same pattern as spotDL-GUI's template)
- GitHub Actions workflow for auto-build/push to Docker Hub on commit (reuse the working workflow from spotDL-GUI, updated action versions from the start — no Node.js 20 deprecation warnings this time)
- README with install instructions (Docker, Docker Compose, Unraid CA)

**Definition of done:**
- Fresh pull on a clean Unraid box, container boots, Settings configured, a test album fully downloads end-to-end
- GitHub Action builds and pushes successfully with zero warnings

---

### Batch 10 — Hardening pass
**Scope:**
- Error handling audit — every failure mode in the pipeline (no MusicBrainz match, no YouTube Music match, network failure mid-download, disk full, malformed metadata) surfaces a clear, specific error in the UI rather than a silent failure or generic 500
- Rate limit handling for MusicBrainz (they are strict — 1 request/second per their usage policy)
- Load test: seed a large library, hammer the queue with 50+ simultaneous adds, confirm no deadlocks or corrupted queue state
- Final performance pass against the Section 9.5 benchmarks

**Definition of done:**
- All of Section 9.5's target benchmarks are met on the seeded large dataset
- No known silent failure paths remain

---

## 11. Open questions / assumptions log

### Resolved during Batches 1–5 review (2026-07-12)

Four decisions were flagged by the implementing agent as blockers before Batch 6/7. All four are now resolved and reflected inline in the relevant sections above:

1. **Dashboard mockup** — was missing from the repo. Now provided at `/design/dashboard-reference.html`. Section 8 updated to point at it directly.
2. **Playlist data model** — `Playlist`/`PlaylistTrack` tables added to Section 5 (additive migration). Required for "Complete this playlist" (Section 7.4) to have something to group against.
3. **Cover art on missing artwork** — confirmed current behavior (warn + proceed without art) is correct, not a bug. Section 6 wording softened from "mandatory" to "attempted, non-blocking." Missing-art tracks should be visually flagged in the Library UI (Batch 7).
4. **Add-artist scope** — confirmed row-only for v1 is correct. Full discography pulling/monitoring explicitly deferred to v2 in Section 3's non-goals.

### Original assumptions log

Track anything the agent has to assume here so it can be reviewed and corrected rather than silently baked in:

- **Assumed:** Output formats supported = mp3, flac, m4a, opus, wav, ogg (same set as spotDL-GUI). Confirm if this should change.
- **Resolved:** Spotify integration dropped entirely (see Non-goals, Section 3). MusicBrainz is primary metadata, YouTube Music is fallback metadata + playlist source + audio source. No Premium account or developer app dependency anywhere in the stack.
- **Assumed:** No built-in scheduler for "watch artist for new releases" in v1 — flagged as a backlog item, not built now.
- **Open:** Exact logo asset — placeholder monogram until a real logo is supplied.
- **Open:** Whether genre tagging pulls from MusicBrainz's genre/tag data or is left blank when unavailable — needs a decision before Batch 3.

### Batch 6 additions (2026-07-12)

- **Assumed:** Batch 6's Dashboard scope implies a "Recent Activity" data source that Section 10 doesn't explicitly define. Added `GET /api/activity` — the newest N finished/errored `QueueItem`s joined to `Track`/`Album`/`Artist`, not paginated (always "latest N", no `offset`). Also extended `QueueItemOut` with `artist_name`/`album_title` (queue rows otherwise can't render "Artist · Album" subtitles). Both are small additive extensions, no schema changes.
- **Noted:** The dashboard-reference mockup's search placeholder text and one "Added artist watch" activity example are relics of an earlier product ("SpotGet") this mockup was adapted from — branding was corrected to Grooverr and the artist-watch example dropped (matches the Section 3 non-goal), everything else ported as-is.

### Batch 7 additions (2026-07-12)

- **Assumed:** Section 8 lists no dedicated "Playlists" screen, but Batch 7's scope explicitly requires a "Complete this playlist" action to exist somewhere. Placed a compact Playlists panel at the bottom of the Library page, listing each playlist with X/Y tracks and a Complete action — the most direct placement given the existing screen list. Worth a dedicated Playlists screen/tab in a later batch if playlists become a primary use case rather than an incidental one.
- **Assumed:** Track.has_artwork (Section 11 Batch 7 backend note) drives the "flag missing-art tracks" decision — surfaced in Album Detail's per-track row as a small "no artwork" label, not at the album-grid level (art presence is a per-file post-download fact, not a metadata-source fact the album card already shows via cover_art_url).
- **Fixed (pre-existing bug, not introduced by Batch 7):** `_find_or_create_artist`/`_find_or_create_album` skipped their dedup lookup entirely when the resolved name/title was `None`, so two tracks added with no artist/album metadata at all would each mint a fresh "Unknown Artist"/"Unknown Album" row instead of sharing one. Surfaced by testing the new playlist-add path, but applies to every add-to-library flow. Fixed by searching on the effective (fallback-applied) name in both cases.
- **Found (real, unfixed):** Testing the playlist-add path with synthetic malformed video IDs (6 characters, not YouTube's 11) revealed that `find_audio_source` trusts an existing `youtube_video_id` on a resolved track completely unconditionally — no duration cross-check, unlike the search-based matching path (Section 7.3's "duration matching... is the primary anti-mismatch signal"). yt-dlp/YouTube resolved the malformed ID to *some* real 7-minute video and it downloaded successfully with correct-looking tags, silently mismatched. This means any track that arrives with a video ID (search results, playlist imports) has zero anti-mismatch protection before download. Flagging for Batch 10 (hardening pass, "malformed metadata" is explicitly in scope) — likely fix is a duration sanity check against the *download's actual length* post-fetch, or re-validating the video id's metadata before committing to the download.
- **Fixed (found via live browser testing):** the Queue screen's error-status Pill had no max-width and a JS-truncated string still ~2x wider than its 92px grid column, visually overlapping and clipping the Retry button. Pill now truncates defensively via CSS regardless of caller string length; the Queue screen (which has more horizontal room than the Dashboard's compact teaser) got a wider dedicated column.

---

*End of specification.*
