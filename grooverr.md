# Grooverr — Build Specification

**Status:** Batches 1-10 complete and verified live (last updated 2026-07-16) — v1 is built and shipping; remaining work tracked as dated findings in Section 11, not open batches. This document remains the source of truth for architecture decisions and is still updated in place as real-world use surfaces gaps.
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
- Automatic "watch this artist for new releases" (may be a v2 feature — flagged in backlog, not built now). **Decision (resolved 2026-07-12, clarified 2026-07-14):** this non-goal is about **standing, automatic monitoring** — Grooverr does not watch an artist and auto-queue new releases as they come out, that's the deferred v2 feature. It does **not** mean an artist can't be browsed on demand. "Add to library" on an Artist search result creates the `Artist` row only, with no downloads triggered — but the user must still be able to open that artist and see/select from their actual discography (Section 7.1.1, added 2026-07-14). Conflating "no auto-monitoring" with "no browsing" left a real gap in the v1 build: clicking through to an artist did nothing, discovered during real-world testing.
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
  m3u_path (nullable)      -- path to the generated .m3u8 file, null until first generated
  m3u_generated_at (nullable)
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

### 6.1 Playlists on disk — no audio duplication (decision resolved 2026-07-13)

A track added via a playlist import goes through the **exact same pipeline and lands at the exact same path** as if it had been added via album or artist search — there is only ever one physical copy of a given track's audio file, regardless of how many playlists reference it or whether it's also part of a "properly" downloaded album. This matters for two reasons: duplicating audio per-playlist would multiply storage for every popular track, and it would break the completeness/dedup logic already built in Batches 2–5, which assumes one canonical `Track` row per recording.

Playlists are represented on disk as **generated `.m3u8` files**, not folders of audio:

```
{MusicRoot}/Playlists/{PlaylistName}.m3u8
```

Example:
```
/music/Playlists/Weekend Vibes.m3u8
```

This is the standard mechanism Plex, Navidrome, Jellyfin, and Plexamp (as a Plex client) are all built around — each of them can scan `.m3u`/`.m3u8` files sitting in the library and surface them as a native playlist, without needing the referenced audio to live inside the playlist file's own folder. Exact auto-import behavior varies slightly by server (e.g. some watch the whole library root, some need the playlists folder specifically included in the scan path) — treat this as **best-effort native integration**, not a hard guarantee for every server/version. Worst case, the `.m3u8` is still a completely standard, portable playlist file openable in any music player even if a given server doesn't auto-import it.

**M3U8 generation rules:**
- Entries reference tracks via **relative paths from the playlist output folder**, so the whole `{MusicRoot}` remains portable/movable as a unit
- Only tracks with `Track.status = downloaded` are included — a playlist referencing a not-yet-downloaded file would be a broken entry in Plex/Navidrome/etc., so the file is regenerated (not written once and left stale) every time a track in that playlist finishes downloading
- Track order follows `PlaylistTrack.position`
- `Playlist.m3u_path` and `Playlist.m3u_generated_at` are updated on every regeneration
- Illegal filesystem characters in the playlist name are sanitized using the same rule as track/album names (Section 6's illegal-character rule above)
- **The playlist output folder itself defaults to `Playlists/` relative to `{MusicRoot}` but is Settings-configurable** (decision resolved 2026-07-13, implemented in Batch 8) — the same pattern as the track path template. Regenerating a playlist after this setting changes must write to the new location, not silently keep using the old default.

**Where this lands in the batch plan:** the core M3U8 generation (fires on "track status flips to downloaded") landed as a small addition to the download pipeline (Section 7.3) ahead of schedule — implemented directly rather than waiting for a dedicated batch, since Claude Code was already mid-rebuild of the Library/Albums section when this decision was made. Two bugs were found and fixed during that work: a circular import (orchestration moved to `app.downloader.m3u`, which has no dependency on `app.runtime`/`app.queue`) and a silent collision bug in SQLModel's `session.exec()` — it returns bare scalars for single-column selects, not `Row` tuples, so `row[0]` was slicing the first *character* off a stored path instead of indexing a tuple, meaning two same-named playlists silently collided onto one file. The output-folder configurability follow-up is scoped into Batch 8 above, since that's where the settings persistence layer is being built anyway.

---

## 7. Core workflows

### 7.1 Search & Add
1. User types a free-text query, or pastes a YouTube Music URL, into the search bar
2. If it's a URL: detect type (track/album/artist/playlist) and resolve directly
3. If it's free text: **a search-type selector (added 2026-07-14) narrows what's actually being queried** — "All" (default, current mixed Tracks/Albums/Artists behavior), "Title," "Album," or "Artist." Selecting **Artist** mode queries MusicBrainz's artist index directly (name-based artist search, not recording/title search) — this is a structural fix, not a ranking tweak, since tribute tracks and mashups by unrelated artists cannot appear in artist-index results at all, regardless of what their titles contain. Selecting Title/Album mode similarly scopes the query to that entity type only. "All" mode retains the existing mixed-section results and remains useful for casual/uncertain browsing.
4. Results shown as cards. In **Artist** mode specifically, clicking a result card (not just an "Add to library" button) opens Artist Detail (7.1.1) directly — this is the primary way a user is expected to reach an artist's full discography, replacing reliance on free-text ranking quality for that use case.
5. In Title/Album/All modes, results are shown as cards (track/album/artist/playlist), user picks one or more to add
6. Adding creates `Album`/`Track` rows with `status=missing`, and enqueues a `metadata_resolve` job per track (or per album, resolving all child tracks in one pass where the source supports it)

**Free-text ranking note (added 2026-07-14, found during real-world testing, superseded in part by the search-type selector above):** a query that reads as an artist name (e.g. "linkin park") in **All** mode should still not surface unrelated tracks/albums whose *title* merely contains that phrase ranked alongside or above the actual artist's own catalog — prefer artist-credit matches over title-substring matches when scoring All-mode results, on top of Batch 5's existing Jaccard re-ranking. This remains a minor ranking-quality item for All mode specifically; Artist mode and Artist Detail (7.1.1) solve the problem structurally and are the recommended path, not a ranking fix.

### 7.1.1 Artist Detail — browsing a discography (added 2026-07-14)

**Gap found during real-world testing:** clicking an Artist result in Search did nothing beyond "Add to library" (which only creates the bare `Artist` row per Section 3's non-goals). There was no way to actually see or select from that artist's releases. This is a missing screen, not a deferred feature — the deferred v2 feature is *automatic* monitoring (Section 3), not manual browsing, and the two got conflated during implementation.

**Fix:** clicking through to an artist (from a Search result, or from the Artist row wherever it appears) opens an **Artist Detail** view:
1. Fetch the artist's release-groups directly from MusicBrainz **by artist MBID** (`/ws/2/release-group?artist={mbid}&type=album|single|ep`), not by free-text search — this is a structured browse against a known entity, so it returns only that artist's actual official releases, with none of the tribute/mashup/parody pollution that a text search surfaces
2. Display as a card grid (reuse the Library album-card component and completeness-badge pattern — Section 8). **Filter tabs are required, not optional (strengthened 2026-07-15, found during real-world testing):** All / Album / Single / EP / Compilation as segmented tabs above the grid, same pattern as the Library's Albums/Playlists tabs (Section 8). The release-type badge in the corner of each card (already implemented) is not enough on its own — confirmed during real-world testing with a discography of 10+ releases where singles, compilations, and albums were visually mixed together and the corner badge was too subtle to scan quickly. Tabs make the type immediately actionable (jump straight to "Album" to skip anniversary-reissue singles and B-side compilations), not just visible.
3. Each release card gets its own "Add to library" action (same per-album behavior as elsewhere), plus an artist-level "Add entire discography" bulk action for convenience. **Decision (resolved 2026-07-15, post-audit):** the bulk action must reuse the existing single-album add pipeline, fired once per release, returning immediately — not a bespoke synchronous resolve loop. The audit found the original synchronous implementation blocked a single HTTP request for ~7.5 minutes on a large discography (219 releases), head-of-line-blocked interactive search behind the shared MusicBrainz rate limiter for that entire window, and re-paid the full resolution cost on any retry after partial failure. Routing through the same per-album path already used by manual "Add to library" clicks fixes both problems at once: progress surfaces through the existing Queue UI (Section 7.5) rather than a blocked request, and retries are cheap because that path already dedups correctly (the bulk-specific loop was the only code that didn't).
4. The bulk action is a **one-time, user-triggered snapshot** of the artist's current catalog — it is explicitly not a standing watch/monitor (that remains the deferred v2 feature). Enqueuing everything visible right now is fine; there is no future-release awareness

**New endpoint required:** `GET /api/artists/{id}/discography` (or equivalent) — browses MusicBrainz by MBID as above, paginated per Section 9.2's requirements same as every other list endpoint.

**Definition of done for this fix:**
- Clicking through to Linkin Park's Artist Detail shows their actual studio albums/singles/EPs, not fan content
- No tribute albums, mashups, or same-title-different-artist tracks appear anywhere in the Artist Detail view (structural guarantee from browsing by MBID, not a ranking heuristic)
- "Add entire discography" enqueues every currently-visible release without creating a standing monitor

### 7.2 Metadata resolution pipeline
1. Worker picks up a `metadata_resolve` QueueItem
2. Query MusicBrainz for canonical release/track data using best available identifiers (ISRC if we have it, else artist+title+album fuzzy match)
3. If no MusicBrainz match found, fall back to YouTube Music metadata
4. Populate/patch the `Track`/`Album`/`Artist` rows with whatever was found
5. Enqueue a `download` QueueItem for the track

### 7.3 Download pipeline
1. Worker picks up a `download` QueueItem
2. Search YouTube Music (`ytmusicapi`) for a best match using title + artist + duration (duration matching within a few seconds tolerance is the primary anti-mismatch signal). **This duration cross-check is mandatory on every download, including when the `Track` row already carries a `youtube_video_id`** — a pre-existing ID must never be trusted blindly. Fetch the candidate video's duration before downloading and compare it against `Track.duration_seconds` using the same tolerance as a fresh search match; if it falls outside tolerance, treat it as no match (fall through to a fresh search, or surface an error if that also fails) rather than downloading it. **Decision (resolved 2026-07-13):** this was found during Batch 6 testing as a silent-mismatch bug affecting any track with a pre-populated video ID (search results, playlist imports) — fixed immediately rather than deferred to Batch 10, since it's a correctness gap in already-specified behavior, not new hardening scope.
3. If no confident YouTube Music match, fall back to a plain YouTube search via the same matching logic
4. `yt-dlp` fetches the audio. **Format selector must be `bestaudio/best` (or equivalent broad fallback chain) with no bitrate/codec constraint applied at this stage** — the job's `requested_quality` ceiling is enforced during post-processing (step 5), never at yt-dlp's format-selection stage. **Decision (resolved 2026-07-15, found during real-world testing):** a rigid selector (requiring a specific bitrate/codec/container that most YouTube streams don't actually have) caused "Requested format is not available" failures across every download tested — not an isolated bad video, a systemic selector bug. YouTube's available formats vary per video and change over time; any selector demanding an exact match rather than grabbing whatever audio stream exists will eventually fail on everything. Always download the best raw audio available, decoupled entirely from the user's quality ceiling. **Ongoing maintenance note (added 2026-07-16, Section 11 item 17):** this class of failure isn't necessarily a one-time bug to fix and forget — YouTube changes its internal extraction requirements often enough that yt-dlp ships frequent releases just to keep up (anti-bot/PO-token/challenge-solving enforcement is described upstream as an actively evolving, per-request experiment, not a fixed rule). The pinned `yt-dlp` version in `backend/requirements.txt` should be periodically checked against upstream releases, not just pinned once at build time — a version that's fine today can start failing without any change on Grooverr's own side.
5. Post-process: **transcode to the target format and enforce the `requested_quality` ceiling here via ffmpeg** (downward only — never upscale a lower-bitrate source to fake a higher ceiling; if the source is 128kbps opus and the ceiling is 320kbps mp3, the output is genuinely only as good as the 128kbps source, transcoded), embed tags via `mutagen`, write to the path per Section 6
6. Update `Track.status = downloaded`, set `file_path`, `bitrate`, `audio_source`
7. On any failure at any step: `Track.status = error`, `error_message` populated, **do not silently drop the job** — it must be visible in the UI queue as an error state the user can retry

### 7.4 Library completeness tracking
- Every album's card in the Library view shows `X of Y tracks` — `Y` comes from the metadata source's `total_tracks`, `X` is a live count of `Track.status = downloaded` for that album
- "Complete this album" button enqueues `download` jobs for every track in that album currently `status != downloaded`
- Same pattern for a playlist: "Complete this playlist" queues everything not yet downloaded. As each queued track finishes downloading, the playlist's `.m3u8` file (Section 6.1) regenerates to include it — the playlist becomes progressively more complete on disk in real time, same as the completeness badge does in the UI.

### 7.5 Queue system
- Two visually distinct sub-queues in the UI: **Resolving** (metadata jobs) and **Downloading** (audio fetch jobs) — mirrors the dashboard mockup's "Active Queue" panel
- Each item shows live progress (SSE-pushed), with retry/cancel actions per item
- Queue persists across container restarts (it's just rows in SQLite with `status=queued`/`active` — on startup, any job stuck in `active` from an unclean shutdown gets reset to `queued`)

### 7.6 Removal & cleanup (added 2026-07-16, found during real-world testing)

**Gap found:** there was no way to clear failed/stale queue items, and no way to delete anything from the library at all — no track, album, artist, or playlist could be removed once added. Every workflow so far has been additive; this closes that gap. Discovered when a user hit a batch of stuck failed downloads (pre-dating a bugfix) with no way to clear them and retry cleanly.

**Queue bulk actions** (extends 7.5):
- Individual cancel already exists per Section 7.5 — keep it.
- Add bulk actions: **"Clear failed"** (removes every `QueueItem` with `status=error`) and **"Clear completed"** (removes every `status=done` item that's just accumulating in the list). Both are metadata-only operations — they never touch downloaded files or `Track` rows, only the `QueueItem` audit trail.
- New endpoints: `POST /api/queue/clear?status=error` and `POST /api/queue/clear?status=done` (or a single endpoint taking a status filter — implementer's choice, but both must exist as distinct one-click UI actions, not just an equivalent-but-hidden filter+individually-cancel workflow).

**Library deletion** — new capability across every entity type:
- `DELETE /api/library/tracks/{id}`
- `DELETE /api/library/albums/{id}` (cascades to child tracks)
- `DELETE /api/library/artists/{id}` (cascades to child albums/tracks — requires confirmation, see below, since this can be a large blast radius)
- `DELETE /api/library/playlists/{id}` (removes the `Playlist`/`PlaylistTrack` rows and the generated `.m3u8` file; does **not** delete the underlying tracks, since those belong to their Album per Section 6 and may be referenced by other playlists)

**The delete-files decision (Lidarr/Sonarr pattern, adopted here):** every delete action takes an explicit `delete_files: bool` parameter.
- `delete_files=false` (default): removes the database rows only. The physical audio file(s) stay on disk, untracked by Grooverr. Useful for "I added the wrong thing, but I already have other files in that folder I don't want touched" or "I want to manage this manually now."
- `delete_files=true`: removes the database rows **and** deletes the actual audio file(s) from `{MusicRoot}`. This is irreversible and must require explicit confirmation in the UI (a modal, not a single click) — no accidental mass-deletion of real files.
- Deleting a track that belongs to one or more playlists must also remove the corresponding `PlaylistTrack` rows and trigger an M3U8 regeneration (Section 6.1) for every affected playlist, so no playlist file is left pointing at a file that no longer exists or is no longer tracked.
- If deleting an album/artist leaves an empty folder on disk (all tracks removed with `delete_files=true`), clean up the now-empty directory too — don't leave empty `Artist/Album (Year)/` folders scattered through the music library.

**UI:**
- Queue screen: "Clear failed" and "Clear completed" buttons alongside the existing per-item cancel, per sub-queue (Resolving/Downloading)
- Library: a delete action on Album Detail, Artist Detail, and individual track rows, plus on Playlist cards. Triggers a confirmation modal offering the `delete_files` choice explicitly — e.g. "Remove from library" vs. "Remove and delete files" as two distinct buttons, not a checkbox easy to miss

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
2. **Search** — search bar (same as dashboard's, or a dedicated larger version), result cards for tracks/albums/artists/playlists, "Add to library" action per result. Clicking through an Artist result (not the "Add to library" button, which stays row-only per Section 3) opens **Artist Detail** (Section 7.1.1) — that artist's actual discography browsed by MusicBrainz ID, with per-release add actions and a bulk "add entire discography" option.
3. **Library** — tabbed view: **Albums** and **Playlists** as segmented tabs within the one Library screen (not a separate top-level nav item, and not a buried footer panel — **decision resolved 2026-07-13**). Albums tab: full browsable grid of all albums, filterable by artist / completeness status / format, each card shows the completion badge pattern from the dashboard mockup. Clicking an album opens an **Album Detail** view listing every track with its individual status (downloaded / missing / queued / error) and a per-track "download this one" action. Playlists tab: same card-grid pattern and completeness badge treatment as Albums, since playlists need the identical "X of Y tracks" + "Complete this playlist" UI that albums already have — reuse the same components rather than building parallel ones.
4. **Queue** — full queue view (not just the dashboard teaser), split into Resolving / Downloading tabs, with retry/cancel per item, plus **"Clear failed" / "Clear completed" bulk actions** (Section 7.6, added 2026-07-16)
5. **Settings** — API credentials (MusicBrainz doesn't need a key but rate-limits by user-agent string; optional YouTube cookie file upload exactly like the spotDL-GUI pattern already proven), default quality ceiling, output path template editor, theme toggle. **MusicBrainz user-agent field clarity (added 2026-07-14, found during real-world testing):** the shipped default was a literal unfilled placeholder (`https://github.com/you/grooverr` — doesn't resolve to anything), which is exactly the kind of thing MusicBrainz's usage policy cares about, since they expect a working contact URL identifying the application. Fix required: (a) the default value must point at the real project repo, not a template placeholder; (b) add a short help line under the field clarifying that this identifies the *application* to MusicBrainz, not the individual user — most people never need to change it, and it is not a personal username/nickname field. Only worth customizing if running a modified fork or wanting a distinct contact string for a specific deployment. **Version footer (added 2026-07-16, found during real-world testing):** a small, unobtrusive footer at the bottom of the Settings screen showing the running build's git commit SHA (short form) and build timestamp. Found necessary after repeated confusion in this project (both here and in an earlier related build) about whether a deployed container was actually running the latest fix or a stale image — the only way to check was manually diffing container behavior against expected fix output, which is slow and error-prone. This must be baked in at Docker build time (not computed at runtime, which would just show the same value regardless of what's actually running), sourced from the real commit being built, and exposed via a small `GET /api/version` endpoint the frontend footer reads from.

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
- Library screen with **Albums / Playlists tabs** (Section 8 — decision resolved 2026-07-13), both tabs sharing the same virtualized grid component (Section 9.4) — must be tested against a seeded large dataset on both tabs, not just a handful of albums
- Album Detail view (per-track status list, individual retry/download actions)
- Full Queue screen (Resolving/Downloading tabs, retry/cancel)
- "Complete this album" / "Complete this playlist" actions
- Verify the Batch 6 duration cross-check fix (Section 7.3) holds under the Library/Queue UI's real usage patterns — e.g. retrying a track from the Queue screen must go through the same cross-check, not a separate retry code path that bypasses it
- **M3U8 playlist file generation** (Section 6.1, decision resolved 2026-07-13) — backend addition to the download pipeline: on every track status flip to `downloaded`, regenerate the `.m3u8` for any playlist that track belongs to. Playlists tab in the UI should show the current `m3u_path` (or an indicator that it hasn't been generated yet for an empty/all-missing playlist).

**Definition of done:**
- Library screen tested against 1,000+ seeded albums **and** a realistic set of seeded playlists, scroll performance verified against the Section 9.5 benchmarks on both tabs
- Album completeness badges are accurate and update live as tracks finish downloading
- Playlist completeness badges (same component, reused) behave identically
- A seeded playlist's `.m3u8` file is inspected directly on disk and confirmed to: contain only downloaded tracks, use correct relative paths, reflect `PlaylistTrack.position` ordering, and regenerate correctly as more of its tracks finish downloading mid-test

---

### Batch 8 — Settings screen + credential handling
**Scope:**
- Settings UI: MusicBrainz user-agent config, YouTube cookie file upload (reuse the exact drag-and-drop pattern already proven working in spotDL-GUI — use a `<label for=>` wrapping the hidden file input, not an `onclick` handler, per the lesson learned there), default quality ceiling, output path template editor with live preview
- **Playlist output folder is now a Settings-configurable path** (decision resolved 2026-07-13), stored under the same `Settings` key/value mechanism as the track path template. Default remains `Playlists/` relative to `{MusicRoot}` (Section 6.1), but a user with an existing Navidrome/Plex setup that expects playlists somewhere else shouldn't need a code change to accommodate it. This was flagged as a hardcoded assumption during the M3U8 implementation — folding the fix into this batch since it's already building the settings persistence layer, rather than a separate follow-up pass later.
- Credentials stored in `/config` volume, never in the music output volume (same security pattern as spotDL-GUI)

**Definition of done:**
- Settings persist across container restarts
- Cookie file upload works correctly in Chrome, Firefox, and Edge (this bit specifically bit us before — verify in all three)
- Changing the playlist output folder setting and regenerating an existing playlist's M3U8 correctly writes to the new location, not the old default

---

### Batch 9 — Packaging & Unraid template
**Scope:**
- Final Dockerfile hardening (multi-stage build, minimal final image size)
- `docker-compose.yml`
- Unraid Community Applications XML template (`/config` and `/music` volumes, same pattern as spotDL-GUI's template)
- GitHub Actions workflow for auto-build/push to Docker Hub on commit (reuse the working workflow from spotDL-GUI, updated action versions from the start — no Node.js 20 deprecation warnings this time)
- README with install instructions (Docker, Docker Compose, Unraid CA)
- **Version footer build mechanism (added retroactively 2026-07-16, found during real-world testing):** the Dockerfile must accept build args for git commit SHA and build timestamp (`--build-arg GIT_SHA=$(git rev-parse --short HEAD)`, `--build-arg BUILD_DATE=...`), write them to a small file baked into the image at build time (e.g. `/app/version.json`), and the GitHub Actions workflow must pass these automatically on every build (`${{ github.sha }}` is available directly in Actions, no extra step needed). A new `GET /api/version` endpoint reads that baked file and the frontend footer (Section 8, Settings screen) displays it. This is specifically to make "is this container actually running the fix I think it's running" a 2-second visual check instead of a manual `docker exec` diagnostic session — found necessary after this exact confusion cost real debugging time on a real bug (Section 11 item 17/18).

**Definition of done:**
- Fresh pull on a clean Unraid box, container boots, Settings configured, a test album fully downloads end-to-end
- GitHub Action builds and pushes successfully with zero warnings
- The version footer's displayed commit SHA matches the actual commit that was built — verify by checking out a specific commit, building it, and confirming the footer shows that exact SHA, not a stale or generic value

**Completed and verified live (2026-07-14):**
- Multi-stage Dockerfile (Node build stage discarded, only `frontend/dist` copied into the final Python image), non-root by default via `entrypoint.sh` (PUID/PGID remap using `setpriv`, LinuxServer.io/Unraid convention, `tini` as PID 1), `/api/health` HEALTHCHECK.
- `docker-compose.yml`, `unraid/grooverr.xml` (CA template, PUID/PGID default to Unraid's own `99:100`, not the Dockerfile's generic `1000:1000`), `.github/workflows/docker-publish.yml`, `README.md`.
- Verified live at the time: real image build with zero warnings; real container boot with a genuine host bind-mount (not Docker's anonymous-volume fallback) for `/music` and `/config`; correct non-root privilege drop and PUID/PGID remap confirmed via the actual process tree (`docker top`, not `docker exec` — the latter always starts a fresh root-owned process regardless of the entrypoint's own privilege drop, so it's not evidence of anything); a real search→add→download through the container's REST API landing on the host at the correct path with correct in-container file ownership. Image size ~955MB (~461MB of that is the ffmpeg/tini/curl apt layer) — not reduced further, judged reasonable for v1.
- **Not verified at the time, and this gap mattered later:** a literal Unraid host, or a real GitHub Actions run actually succeeding end-to-end. It didn't — the workflow's trigger was `branches: [main]` while this repo's actual default branch is `master`, so every push to `master` silently never triggered an automated build. This went unnoticed for two days and directly caused Section 11 items 17-18: three full rounds of yt-dlp investigation ran against local/sandboxed Docker builds because the *real* production container was stuck on whatever image had last been pushed manually, never automatically updated by any of the intervening fixes. Fixed 2026-07-16 (`branches: [master]`), together with two more stale `main`-branch references caught in the same pass (`unraid/grooverr.xml`'s own `TemplateURL`, `README.md`'s manual-install instructions) — both were silently 404ing. The version footer (item 19) exists specifically so this class of "is the real container actually on the fix" question never again requires a multi-round investigation to answer.

---

### Batch 10 — Hardening pass
**Scope:**
- Error handling audit — every failure mode in the pipeline (no MusicBrainz match, no YouTube Music match, network failure mid-download, disk full, malformed metadata) surfaces a clear, specific error in the UI rather than a silent failure or generic 500
- **Rate limit handling for MusicBrainz — must be a single, global, shared rate limiter used by every code path that calls MusicBrainz, not a per-module or per-endpoint limiter (clarified 2026-07-14).** As of this clarification, that includes at minimum: interactive search (Section 7.1, all modes including the new Artist mode), the metadata resolution worker (Section 7.2), and Artist Detail's discography browse (Section 7.1.1). A user searching interactively while a large batch (playlist import, "add entire discography") is resolving in the background must not be able to push the *combined* request rate over MusicBrainz's ~1 req/sec policy — if each of those call paths has its own independent limiter instance, the combined rate can exceed the limit even though each individually appears compliant. Verify with a concurrent test: fire an interactive search while a multi-album resolve job is mid-flight, confirm total MusicBrainz request timing never drops below ~1 second apart across *all* sources combined.
- Load test: seed a large library, hammer the queue with 50+ simultaneous adds, confirm no deadlocks or corrupted queue state
- Final performance pass against the Section 9.5 benchmarks

**Definition of done:**
- All of Section 9.5's target benchmarks are met on the seeded large dataset
- No known silent failure paths remain
- Confirmed via the concurrent test above: exactly one MusicBrainz rate limiter instance exists application-wide, not one per module

**Completed and verified live (2026-07-15):**
- **Rate limiter**: re-audited given the strengthened scope (search + worker resolve + Artist Detail browse, not just the two paths checked in round 1). Confirmed all three still resolve through the one process-wide `app.runtime.resolver.mb` instance (`app/api/search.py`, `app/api/artists.py`, `app/queue/pipeline.py` via `main.py`'s `Pipeline(resolver=runtime.resolver)`). Added `test_concurrent_search_and_worker_resolve_share_rate_limit` (`backend/tests/test_rate_limiter.py`) — the exact DoD scenario (interactive search racing a multi-track `metadata_resolve` job, the Section 7.2 worker path, not the Artist Detail browse the round-1 test already covered) — using `MetadataResolver.resolve_track` directly, the same call `Pipeline._resolve` makes. Real logged timestamps: `t+0.000s /ws/2/recording`, `t+1.004s`, `t+2.008s`, `t+3.015s` — gaps `1.003s/1.004s/1.007s`, all ≥0.95s. Both this and the pre-existing browse test pass.
- **Load test**: new `backend/tests/test_load.py`, run against the real ASGI app via `httpx.ASGITransport` (true asyncio concurrency, not TestClient's serialized sync client) so it exercises real concurrent SQLite writes under WAL mode. 55 distinct albums added fully concurrently → exactly 55 Album rows, 165 Track rows, 165 download jobs, zero duplicates, zero exceptions. A second, more adversarial test fires 50 concurrent requests to add the *same* album (the "did-I-just-double-click" race) → exactly 1 Album row, 5 tracks — `_find_or_create_album`'s check-then-insert has no race under real concurrent load.
- **Error handling audit**, all five named failure modes: (1) no MusicBrainz match — existing specific message from `Pipeline._resolve`, tested; (2) no YouTube Music match — `DownloadEngine.download_track` raises a specific `DownloadFailure`, tested; (3) network failure / unavailable video (the exact class of bug just fixed in round 2) — live-verified with a real nonexistent video id (`aaaaaaaaaaa`) through the full real `DownloadEngine`, end to end: surfaces as a clean `DownloadFailure('yt-dlp failed for aaaaaaaaaaa: ERROR: [youtube] aaaaaaaaaaa: Video unavailable')`, exactly what lands on `Track.error_message` — never a raw stack trace or generic 500; (4) malformed/missing metadata (genre/label/popularity-class fields) — both `app/resolver/musicbrainz.py` and `app/resolver/ytmusic.py` already enforce safe `.get()`-only field access as a hard requirement (module docstrings), with extensive existing malformed-payload test coverage (`test_musicbrainz.py`, `test_ytmusic.py`); (5) disk full — `DownloadEngine`'s final `shutil.move` is wrapped in `except OSError`, raising a specific `DownloadFailure` with the target path. Also confirmed at the worker-pool level (`app/queue/workers.py`): `Pipeline.process()`'s top-level `except Exception` means no failure of any kind can escape a worker task or leave a job stuck — this backstops all five modes structurally, not just individually.
- **Performance benchmarks (Section 9.5), real numbers against a live-seeded 2,000-album/20,000-track dev database** (`python -m app.api.seed 2000`), measured with Playwright against the real running frontend+backend, not synthetic/mocked timings:
  - Library grid initial render (first card visible): **209–278ms** across repeated runs (target: <1s)
  - Scroll performance over the 2,000-album virtualized grid: **~234–240fps average, worst single frame 16.8ms** (~59.5fps floor) (target: 60fps)
  - Add-to-library optimistic UI update: **1.7ms** from click dispatch to the "Adding…" pending state appearing in the DOM, measured via in-page `requestAnimationFrame` polling against a real Artist Detail add click (target: <200ms)
  - Dashboard stat row: verified empirically via a SQLAlchemy `before_cursor_execute` listener, not just code inspection — **exactly 2 SELECT queries fired**, 18ms wall time, regardless of the 2,000-album/12k-track dataset size (matches the endpoint's own docstring: "Two aggregate queries total... never N+1")

---

## 11. Open questions / assumptions log

### Resolved during Batches 1–5 review (2026-07-12)

Four decisions were flagged by the implementing agent as blockers before Batch 6/7. All four are now resolved and reflected inline in the relevant sections above:

1. **Dashboard mockup** — was missing from the repo. Now provided at `/design/dashboard-reference.html`. Section 8 updated to point at it directly.
2. **Playlist data model** — `Playlist`/`PlaylistTrack` tables added to Section 5 (additive migration). Required for "Complete this playlist" (Section 7.4) to have something to group against.
3. **Cover art on missing artwork** — confirmed current behavior (warn + proceed without art) is correct, not a bug. Section 6 wording softened from "mandatory" to "attempted, non-blocking." Missing-art tracks should be visually flagged in the Library UI (Batch 7).
4. **Add-artist scope** — confirmed row-only for v1 is correct. Full discography pulling/monitoring explicitly deferred to v2 in Section 3's non-goals.

### Resolved during Batch 6 review (2026-07-13)

Fable's Batch 6 report flagged two items needing a decision before Batch 7:

5. **Video ID trust bug** — Batch 6 testing found that a `Track` with a pre-existing `youtube_video_id` (search results, playlist imports) skipped duration cross-checking entirely, risking a silent audio mismatch with no error surfaced anywhere. **Fixed immediately rather than deferred to Batch 10** — Section 7.3 updated to make duration cross-checking mandatory regardless of whether the video ID is fresh or pre-existing. Treated as a correctness gap in already-specified behavior (7.3 already established duration matching as "the primary anti-mismatch signal"), not new hardening scope, hence not deferred.
6. **Playlists screen placement** — not dictated by the original spec. Decided: **tabs within the Library screen** (Albums / Playlists), reusing the same virtualized grid and completeness-badge components rather than a separate top-level nav item or a buried footer panel. Section 8 and Batch 7's scope updated accordingly.

### Resolved during Batch 7 kickoff (2026-07-13)

7. **Playlist folder structure on disk** — user flagged (correctly) that a naive `Music/Playlists/{Playlist}/{Track}` folder tree would duplicate audio files already stored under `Music/{Artist}/{Album}/`, doubling storage and breaking the single-canonical-Track-row dedup logic. **Resolved:** tracks are never duplicated — playlists are represented as generated `.m3u8` files at `Music/Playlists/{PlaylistName}.m3u8`, referencing the canonical track paths via relative links. This is the same mechanism Plex/Navidrome/Jellyfin/Plexamp expect for playlist scanning. Full detail in new Section 6.1; `Playlist.m3u_path` field added to the data model; regeneration hook added to the download pipeline (Section 7.3) and to Batch 7's scope, since Claude Code was mid-rebuild of the Library section when this was caught.

### Resolved during Batch 8 kickoff (2026-07-13)

8. **Playlist output folder configurability** — the M3U8 implementation (item 7 above) shipped with the `Playlists/` folder hardcoded relative to `{MusicRoot}`. Flagged by Claude Code as a reasonable-but-inflexible default. **Resolved:** made Settings-configurable, same mechanism as the track path template, folded into Batch 8 since that's already building the settings persistence layer — see updated Batch 8 scope and Section 6.1. Two unrelated bugs were caught and fixed during the original M3U8 implementation and are worth keeping on record for the eventual full audit: a circular import (`app.api.playlists` → `app.runtime` → `app.queue` → back to itself; moved the orchestration function to `app.downloader.m3u`), and a silent collision bug where `session.exec()` returns bare scalars rather than `Row` tuples for single-column selects — `row[0]` was indexing into the *string* (slicing its first character) instead of a tuple, causing two same-named playlists to silently overwrite each other's M3U8 file. The codebase was audited for the same `row[0]` mistake elsewhere; one other instance was found and confirmed to be using a different, correct API.

### Resolved during real-world testing, post-Batch 9 (2026-07-14)

9. **No artist drill-down / discography browsing** — real-world use surfaced that clicking through an Artist search result did nothing. Root cause: the Section 3 non-goal "no automatic artist monitoring" had been implemented as "no artist detail view at all," which was never the intent — auto-*monitoring* (standing, ongoing) and manual *browsing* (one-time, user-triggered) are different things, and only the former was meant to be deferred. **Resolved:** added Section 7.1.1 (Artist Detail), a new `GET /api/artists/{id}/discography` endpoint that browses MusicBrainz by artist MBID (structured lookup, not free-text search), and clarified the Section 3 non-goal wording so this doesn't get re-conflated. Also flagged a related but distinct free-text search ranking issue in Section 7.1 — a query like "linkin park" surfaced unrelated tracks/albums that merely contain that phrase in their title (fan tributes, mashups, same-title-different-artist), ranked alongside genuine results. The Artist Detail page sidesteps this for the "give me this artist's catalog" use case entirely (MBID browse has no fuzzy pollution by construction); the underlying free-text ranking quality is a smaller, separate improvement, not blocking.
10. **Search type selector** — added a Title/Album/Artist/All mode selector to the Search screen (Section 7.1), giving users a direct way to scope a query rather than relying on mixed-mode ranking. Artist mode queries MusicBrainz's artist index directly and routes into Artist Detail (item 9) on click — this is the primary intended path for "show me everything by this artist," not free-text search.
11. **MusicBrainz rate limiter must be a single shared instance, not per-module** — flagged when reviewing whether the new Artist Detail discography browse (item 9) and search-type-filtered queries (item 10) could push combined MusicBrainz request volume over their ~1 req/sec policy if each call site had its own independent limiter. Batch 10's existing rate-limit-handling scope was underspecified on this point. **Resolved:** Batch 10's scope updated to explicitly require one global rate limiter shared across every MusicBrainz call site (search, resolution worker, Artist Detail), with a concurrent test added to that batch's Definition of Done.
12. **MusicBrainz user-agent settings field** — the shipped default was an unfilled placeholder URL (`github.com/you/grooverr`) that doesn't resolve to anything, which matters because MusicBrainz's usage policy specifically wants a working contact URL in the user-agent string. Also unclear from the UI whether this field expects a personal nickname or is an application-level identifier (it's the latter). **Resolved:** Section 8's Settings screen description updated to require the real repo URL as the default and a help line clarifying the field is not a per-user customization.

### Resolved during real-world testing, round 2 (2026-07-15)

13. **Systemic "Requested format is not available" download failures** — confirmed during real-world testing against a live Artist Detail discography (item 9): every download attempted failed with yt-dlp's format-selector-mismatch error, across six different video IDs with zero successes. Root cause: the format selector used at yt-dlp's fetch stage was too rigid (demanding a specific bitrate/codec/container), and YouTube's actually-available formats vary per video and drift over time — a selector requiring an exact match will eventually match nothing. **Resolved:** Section 7.3 step 4 updated — yt-dlp must always use a broad `bestaudio/best` fallback selector with zero quality constraint at the fetch stage; the user's `requested_quality` ceiling is enforced afterward, during the existing ffmpeg post-processing step (step 5), and only downward (never upscaling a lower-bitrate source to fake a higher ceiling). **Fixed and verified live (2026-07-15):** removed the `bestaudio[abr<=…]` filter from `download_audio`'s format selector in `app/downloader/ytdlp.py`, leaving the ceiling enforced solely by the existing ffmpeg postprocessor step. Ran `download_cli.py` end-to-end (real MusicBrainz resolve → real YouTube Music match → real yt-dlp fetch → real ffmpeg transcode → tags read back off disk) against four distinct real tracks covering different formats/codecs/ceilings: Daft Punk "Give Life Back to Music" (mp3 @ 192kbps — ceiling hit exactly), Queen "Bohemian Rhapsody" (mp3 @ 128kbps — ceiling hit exactly), Dave Brubeck "Take Five" (flac, no ceiling — passthrough), and Linkin Park "In the End" (opus @ 96kbps, same artist as the original bug report). Zero format-selector failures across all four.
14. **Artist Detail needs release-type filter tabs, not just a corner badge** — the release-type badge (Single/Album/Compilation) already existed on each card, but real-world testing against a discography of 10+ mixed releases showed it wasn't enough to actually navigate by — confirmed via screenshot showing albums, singles, and compilations all visually mixed with no fast way to isolate one type. **Resolved:** Section 7.1.1 strengthened from "grouped or filterable" (which had been read as optional and wasn't built) to a hard requirement: All/Album/Single/EP/Compilation as segmented tabs, reusing the same tab pattern already built for Library's Albums/Playlists split (Section 8). **Fixed and verified live (2026-07-15):** added the segmented tabs to `frontend/src/pages/ArtistDetail.jsx`, filtering the already-fetched discography client-side by `album.album_type` (the same field already driving the corner badge) and reusing `VirtualizedCardGrid` as-is — filtered tabs still trigger pagination against the real `hasNextPage`/`fetchNextPage` state, so a sparse type (e.g. "EP") keeps paging through the full catalog until either matches accumulate or the discography is exhausted. Verified with Playwright against the real Linkin Park discography (219 releases, same artist as item 13's real-world catch): each tab's rendered cards carry exclusively that tab's badge type after a full scroll (Album → only "album" badges, Single → only "single", EP → only "ep", Compilation → only "compilation"), screenshot confirmed visually, zero console/page errors.

### Resolved post-full-audit (2026-07-15)

The full-audit pass (per audit-brief.md) found 4 bugs (fixed + verified, full suite 184→188 passing) and flagged 1 item needing a product decision rather than a code fix:

15. **Bulk "Add entire discography" blocks and re-pays on retry** — measured live at ~447 sequential MusicBrainz requests / ~7.5 minutes minimum for a 219-release artist, held inside one synchronous HTTP request, head-of-line-blocking interactive search behind the shared rate limiter the whole time. A retry after partial failure re-resolved everything from scratch rather than skipping already-succeeded albums. **Resolved:** Section 7.1.1 updated — bulk add now reuses the existing single-album add pipeline (fired per-release, returns immediately, progress via the existing Queue UI) rather than a bespoke synchronous loop. This also fixes the retry-cost problem as a side effect, since the per-album path already deduped correctly and the bulk-specific code was the only place that didn't.

The other 4 findings (MusicBrainz browse KeyError recurrence, two silently-ignored Settings fields, missing filename length cap, non-atomic M3U8 writes) were fixed and verified directly during the audit — see commits b54a80a and 69eec99, and the full findings list for detail. One item remains genuinely unverified rather than resolved either way: the non-root container check (Section 9/Batch 9) couldn't be re-confirmed live this session because the Docker daemon wasn't running — last live proof is Batch 9's. Worth a quick recheck next time Docker Desktop is up, before treating it as re-confirmed post-audit.

### Resolved during real-world testing, round 3 (2026-07-16)

16. **No removal capability anywhere — queue or library.** Every workflow spec'd through Batch 10 and the full audit was additive; nothing could be deleted. Surfaced when stuck/failed queue items (pre-dating the round-2 yt-dlp fix) had no clear-and-retry path, and separately when a wrongly-added library entry had no delete option at all. **Resolved:** new Section 7.6 — queue gets bulk "Clear failed"/"Clear completed" actions; every library entity (track/album/artist/playlist) gets a delete endpoint with an explicit `delete_files` choice (Lidarr/Sonarr pattern: remove tracking only, or remove tracking + delete the real file, never ambiguous/implicit). Deleting a track cascades to its playlist memberships and triggers M3U8 regeneration for any affected playlist; deleting an artist/album with `delete_files=true` also cleans up any resulting empty folders. Confirmation required in the UI before any `delete_files=true` action — this is the first genuinely irreversible action in the product and needs to read as one.

**Fixed and verified live (2026-07-16):** `POST /api/queue/clear?status=error|done` (`app/queue/service.py`'s new `QueueService.clear`) and four `DELETE` endpoints (`app/api/library.py`'s `delete_track`/`delete_album`/`delete_artist`, `app/api/playlists.py`'s `delete_playlist`), all taking `delete_files: bool = False`. Shared `_delete_track_cascade` helper removes a track's `PlaylistTrack`/`QueueItem` rows before the `Track` row itself — real bug caught mid-implementation: SQLAlchemy's unit of work only orders DELETEs across mapper types via configured `relationship()`s, which these plain `Field(foreign_key=...)` models don't have, so without an explicit `session.flush()` between the child deletes and the parent delete, `PRAGMA foreign_keys=ON` (Section 9.1) rejected the parent's DELETE statement — caught by the new test suite (`backend/tests/test_removal.py`, 18 tests), not found by inspection. `cleanup_empty_dirs` (`app/downloader/paths.py`) walks up from a deleted file's folder removing now-empty directories, stopping at `MusicRoot`. Frontend: `ConfirmDeleteModal` (two explicit buttons, "Remove and delete files" / "Remove from library", never a checkbox) wired into Album Detail, Artist Detail, each track row, and Playlist cards; Queue screen gets "Clear failed"/"Clear completed" buttons (no modal — metadata-only, matches the spec's "one-click" requirement). Verified live against the running dev app (not just the 18 new pytest cases): a real track deleted with `delete_files=false` left its file on disk and disappeared from Album Detail; a second deleted with `delete_files=true` removed the real file; "Clear failed" against 70 real accumulated error jobs in the dev queue dropped `errored_jobs` to 0 without touching the `queued`/`active` counts (live worker churn made a naive before/after `queued` comparison noisy — confirmed unaffected by re-checking against the isolated pytest suite instead, which holds the DB still); artist delete-with-cascade redirected to Library and removed the DB rows. One live-only false alarm caught and ruled out: an ad hoc verification script wrote a `track.file_path` relative to the repo root while the dev server's own cwd was `backend/`, so the file looked "not deleted" — re-run with a path anchored the same way `render_track_path`/`music_root()` actually produce it (as every real download does) confirmed deletion and empty-folder cleanup both work correctly; the mismatch was in the throwaway script, not the app.

### Investigated during real-world testing, round 4 (2026-07-16) — "Requested format is not available" recurrence

17. **Round-2's yt-dlp format-selector fix (item 13) didn't hold** — the same error recurred on entirely different, freshly-added tracks (a Kylie Minogue album) after a confirmed-clean redeploy, ruling out stale queue jobs or a stale container as the explanation. Investigated fresh against the **real Docker image** (built and run for real, not the local dev venv, since that mismatch was suspected as why round 2's local testing didn't catch this):
    - **yt-dlp version:** `2026.7.4`, confirmed via PyPI and GitHub to be the current latest *stable* release as of 2026-07-16 (only a `2026.07.14` nightly/master build is newer — not the recommended production channel). Not stale.
    - **Direct `--list-formats` and real downloads inside the actual container**, no Grooverr code involved: all six of the original round-1 failing video IDs downloaded cleanly. A fresh real 10-track Kylie Minogue album downloaded 100% clean through the actual running API. A 217-release Linkin Park bulk-add generated genuine sustained concurrent worker-pool load — zero `job_type=download` errors surfaced (checked directly against the DB), though it did surface an unrelated real problem: MusicBrainz returned `503 Service Temporarily Unavailable` in bulk partway through the resolve phase — a separate finding, not investigated further here, worth a look if bulk discography adds matter.
    - **Real, verified structural gap found and fixed:** every single yt-dlp invocation logged `WARNING: No supported JavaScript runtime could be found... YouTube extraction without a JS runtime has been deprecated, and some formats may be missing` — the Dockerfile installed no JS runtime, forcing yt-dlp onto its `android_vr` client fallback for every request. **Fixed:** Dockerfile now installs `deno` (yt-dlp's own recommended runtime, per its EJS wiki page), placed at `/usr/local/bin` so it's on `PATH` for the PUID/PGID-remapped non-root runtime user too. Verified in a rebuilt image: `deno-2.9.3` now shows as an available JS Challenge Provider (`[jsc] JS Challenge Providers: bun (unavailable), deno, node (unavailable), quickjs (unavailable)`) and the warning is gone.
    - **PO-token research (external, not guesswork) surfaced a real nuance that complicates the initial theory:** per yt-dlp's current PO Token Guide wiki, PO-token enforcement applies to the `web`/`web_music`/`mweb`/`tv_simply` clients — but explicitly **not** to `android_vr`, the client Grooverr's yt-dlp calls have been falling back to in every single test run (visible in every log as `Downloading android vr player API JSON`). Genuine PO-token coverage (for the clients that do need it) requires a separate plugin, `bgutil-ytdlp-pot-provider` (a JS-runtime script invocation or a standalone sidecar HTTP server) — `deno` alone does not provide it, confirmed live: `PO Token Providers: none` in yt-dlp's debug output, unchanged before and after the deno install. Not added — this is a bigger architectural decision (a new sidecar service or an added per-call script-spawn dependency) that needs an explicit go/no-go, not a silent addition, especially since the client Grooverr actually uses doesn't require it per yt-dlp's own current documentation.
    - **Retest after the deno fix, across a real sample (not just one clean run):** the original 6 IDs + a fresh batch of 12 major-label, globally-popular video IDs (chosen deliberately harder to serve than the niche/older content tested earlier, on the theory that big-label hits are more likely to hit stricter enforcement) — 11 of 12 succeeded cleanly; the one "failure" was a legitimate `ERROR: Video unavailable. This video is not available` (a removed video — a genuinely different, correct error, not the reported symptom). Two of the twelve did hit a *different*, more specific warning even with deno present (`Signature solving failed` / `n challenge solving failed`, because yt-dlp also wants a remote solver-script bundle it doesn't auto-fetch by default) — both still downloaded successfully regardless, since the `android_vr` client's available formats didn't require that particular challenge to be solved for those two videos.
    - **Net result across this investigation: ~28 real, distinct videos tested against the real container (originals + Kylie Minogue album + major-label batch), both before and after the deno fix — zero reproductions of "Requested format is not available."** The deno install is a real, verified, low-risk fix for a real documented yt-dlp gap and is being kept regardless, but it cannot be honestly called "the fix" for round 3's reported failure since that failure was never reproduced here to confirm against. **Not resolved, not closed as fixed** — this is an intermittent, YouTube-side-experiment-shaped problem (per the user's external research) that a ~28-video sample in a sandboxed environment may simply not be positioned to hit, and/or something specific to the production deployment's network/IP/account that a fresh sandbox container doesn't share. Two concrete open threads, blocked on external input this session couldn't supply:
        1. **Cookies** — every test in this investigation ran with **zero** YouTube cookies configured (confirmed: no `youtube_cookies.txt` present in the test container's `/config`), which is the single biggest known difference between this test environment and a real user's browser-authenticated session. Cookie wiring itself was code-reviewed and confirmed correct (`download_audio()` in `app/downloader/ytdlp.py` resolves `resolve_cookies_path()` fresh on every call via a `"unset"` sentinel default, and `DownloadEngine.download_track()` — the only production call site — never overrides it, so a configured cookie file is always picked up live from Settings on every real download). Testing with a genuinely *authenticated* cookie file requires a real cookies.txt exported from an actual logged-in YouTube session in a browser — not something obtainable from this sandboxed environment. Needs Gary to export one (e.g. via a "Get cookies.txt" browser extension) and upload it via Settings, or share it for a further test pass.
        2. If failures continue with cookies configured, the next concrete thing to try is having Grooverr's `download_audio` explicitly retry through yt-dlp's client-fallback order (`--extractor-args "youtube:player_client=web,android_vr,tv"` or similar) rather than trusting whatever yt-dlp picks by default, so a PO-token-related failure on one client doesn't fail the whole job if another client would have worked — not implemented, since there's no reproduced failure yet to confirm this would even help.

### Investigated during real-world testing, round 5 (2026-07-16) — confirming the real deployed container

18. **Real evidence the yt-dlp investigation was never actually testing the deployed environment.** Running `docker exec -it Grooverr yt-dlp --list-formats` directly on the real Unraid host showed the exact "No supported JavaScript runtime could be found... Only deno is enabled by default" warning that the deno fix (item 17) was supposed to have eliminated — meaning the real deployed container was running a stale image throughout at least this round of investigation, most likely as a downstream consequence of the main/master branch trigger mismatch (a separate issue, fixed the same day) silently preventing auto-builds from firing for a period. The command happened to succeed anyway on this particular run (full format list returned via the `android_vr` fallback client), consistent with the "sometimes it works via fallback, sometimes it doesn't" pattern that made this bug hard to pin down — but the deeper lesson is that three rounds of extensive, honest local/sandbox testing never actually verified against the real production container until this check. **Resolved:** added the version footer requirement (item 19 below) specifically so this class of confusion — "am I actually testing the fix, or a stale build?" — becomes a 2-second visual check going forward instead of a multi-round diagnostic saga.
19. **Version footer.** Section 8's Settings screen and Batch 9's packaging scope updated to require a build-time-baked git SHA + build timestamp, exposed via `GET /api/version` and shown in a small Settings footer. See both sections for the full mechanism.

### Investigated during real-world testing, round 6 (2026-07-16) — diffing Grooverr's real invocation against the manual command that never fails

20. **The bare manual `yt-dlp --list-formats <url>` test (zero arguments) never failed across every round; Grooverr's real pipeline did, on the real Unraid host.** Every previous round diffed source code against that manual command rather than what the pipeline actually constructs at call time. Investigated directly: added temporary `logger.debug` instrumentation in `download_audio` (`app/downloader/ytdlp.py`) logging the complete, real `options` dict passed to `yt_dlp.YoutubeDL`, plus a `GROOVERR_YTDLP_VERBOSE=1` env toggle to unsilence yt-dlp's own internal client-selection log (normally suppressed by `quiet`/`no_warnings`), then triggered real downloads through the actual REST API against a rebuilt real container — not a CLI script, the genuine pipeline.
    - **Confirmed identical in every respect except one:** format selector (`bestaudio/best`), `http_headers` (yt-dlp's own default UA — Grooverr sets none), and client landed on (`android_vr`, format 251) were all byte-for-byte identical between the real pipeline invocation and the bare manual command, with zero cookies configured. No `extractor_args`, `proxy`, or `player_client` override exists anywhere in the codebase (confirmed by grepping the whole backend). The **only** structural difference the real options dict ever shows is `cookiefile`, present only when Settings has a cookie file configured — which every prior round's testing never had, since none of those ~40+ manual/CLI tests across 3 rounds ever configured one.
    - **Real bug found and reproduced, not inferred:** `yt_dlp.YoutubeDL` treats a configured `cookiefile` as read-write — on `close()` (fired by the `with` block's `__exit__`), it unconditionally tries to persist rotated cookies back to that exact path, *regardless of whether the actual audio download succeeded*. Reproduced live: uploaded a cookie file via `docker cp` (landing root-owned, `-rwxr-xr-x root root`) into a container running as the real non-root PUID/PGID user (matching the entrypoint's actual privilege-drop pattern) — the download completed in full (audio fetched, converted, tagged) and only then failed, with a raw uncaught `PermissionError: [Errno 13] Permission denied: '/config/youtube_cookies.txt'` thrown from deep inside yt-dlp's `save_cookies()` → `cookiejar.save()` on the way out of the `with` block. `download_audio`'s `except yt_dlp.utils.DownloadError` never catches this — a `PermissionError` isn't that type — so it propagated uncaught past every layer (`engine.py`'s `except YtdlpDownloadError`, `pipeline.py`'s `except DownloadFailure`) up to `Pipeline.process()`'s top-level catch-all, discarding an already-fully-successful download and surfacing a confusing raw exception string as the Track's error message instead of a clean one.
    - **Isolated the trigger condition:** re-ran the identical test with the cookie file uploaded through the real Settings endpoint instead of `docker cp` (so it's written by the already-privilege-dropped process, correctly owned) — single and 4-way-concurrent real downloads both succeeded cleanly, zero errors. So this specific failure requires an ownership/permission mismatch between the cookiefile and the running process to manifest — plausible on a real Unraid `/config` share (pre-existing folder ownership, PUID/PGID not matching the actual share, manual file placement) but not a universal always-fails bug independent of environment.
    - **Fixed:** restructured `download_audio` to call `ydl.download()` and `ydl.close()` as two separate steps (not an implicit `with`-block exit) — a `close()`-time exception (cookiejar write-back or any other cleanup failure) is now caught, logged as a warning, and never discards a download that already succeeded; a genuine download failure still raises normally. Verified live: re-ran the exact reproduction (same root-owned unwritable cookie file, same video id) — `status: downloaded`, real file on disk, `error_message: null`, with a warning logged confirming the write-back still failed as expected but no longer took the job down with it. Two new regression tests (`backend/tests/test_ytdlp_cookies.py`) cover both directions: a close()-time failure after a successful download must not raise, and a genuine download failure must still raise even if close() also fails.
    - **Honest gap, not overclaimed as "the fix":** the reproduced failure's error text is `[Errno 13] Permission denied: ...`, not the literal `"Requested format is not available"` string this whole investigation has chased across three prior rounds. This is a real, structurally-confirmed bug — the single most concrete difference found between the always-succeeding bare manual command and Grooverr's real cookie-enabled pipeline in four rounds of investigation — and it's fixed regardless of whether it's *the* cause of the original symptom. Whether a cookiejar write-back failure (or a related corrupted/torn write from the complete lack of any locking across Grooverr's 3 concurrent download workers, all sharing one cookiefile path) can degrade into a genuine `"no formats"` response on a *subsequent* call is a plausible extension of this bug, not something reproduced or confirmed this round. Next real test, now that the fix ships: retest the original failing video IDs on the real Unraid host with the real cookies.txt in place, across a reasonable sample, and see whether the exact reported symptom recurs at all.

### Root cause found, round 7 (2026-07-16) — authenticated cookies switch yt-dlp onto format-gated clients

21. **The actual root cause of "Requested format is not available", traced through yt-dlp's own source and consistent with every observation from every round.** The decisive report from the real Unraid host: Grooverr fails with that exact error on *ANY* media, while `docker exec -it Grooverr yt-dlp --list-formats <url>` — **inside the same container** — succeeds, landing on the `android_vr` client. That single fact eliminated image staleness, yt-dlp version, deno, network/IP, and permissions in one stroke, leaving only round 6's finding: the sole structural difference between the two invocations is `cookiefile`.
    - **The mechanism, from yt-dlp `2026.7.4`'s own source** (`extractor/youtube/_video.py`, `_base.py`): yt-dlp maintains two separate default client lists — `_DEFAULT_CLIENTS = ('android_vr', 'web_safari')` for anonymous sessions, and `_DEFAULT_AUTHED_CLIENTS = ('tv_downgraded', 'web_safari')` when `is_authenticated` is true. `is_authenticated` is a pure cookie-presence check: `LOGIN_INFO` plus any `SAPISID` variant in the jar — exactly what a real logged-in browser cookies.txt export contains. On top of the list swap, any client without `SUPPORTS_COOKIES` (which `android_vr` lacks — it defaults to `False`) is *removed* from the requested clients for authenticated sessions, with a "Skipping client" warning that Grooverr's `no_warnings=True` suppressed from ever reaching the container logs. So with real account cookies configured, the one client that reliably works (`android_vr`: direct URLs, no PO token required, no JS player required) is structurally excluded, and both remaining clients are currently format-gated: `web_safari`'s formats get skipped as "missing a URL — YouTube is forcing SABR streaming" (captured in this project's own verbose logs), and `tv_downgraded`'s formats are signature-cipher-protected, requiring the EJS solver script that yt-dlp does not auto-download without an opt-in `--remote-components` flag (also captured: "Remote components challenge solver script (deno)... were skipped" → "Signature solving failed: Some formats may be missing"). Zero usable formats from either client → `Requested format is not available` — on every video, deterministically, matching the reported symptom exactly.
    - **Why every prior round missed it:** no local/dev/sandbox test in rounds 1–6 ever had *account* cookies configured — the local dev environment never uploaded any, and round 6's cookie test used non-auth cookies (`CONSENT`/`VISITOR_INFO1_LIVE`), which don't trip `is_authenticated`. The user's real deployment has had a real logged-in cookies.txt uploaded via Settings. Every environment difference chased across three rounds (dev venv vs container, stale image vs fresh, Docker Desktop vs Unraid) was a proxy for the actual variable: cookies configured, or not.
    - **Why it couldn't be fully reproduced even this round:** attempted a live reproduction by uploading a cookies.txt with auth-shaped cookies (`LOGIN_INFO` + `SAPISID` variants, fake values) into the real container — YouTube's server detected the invalid values on the very first request and *cleared them via Set-Cookie*, and yt-dlp's cookiejar write-back persisted the cleared state; `is_authenticated` was already false again by client-selection time, so the download fell back to `android_vr` and succeeded. Holding the authenticated path open requires genuinely valid account cookies, which this environment cannot have. The mechanism is therefore traced and sourced rather than end-to-end reproduced here — final confirmation is the user's next real download on Unraid.
    - **Fixed (the fallback the user asked for):** `download_audio` now retries exactly once *without* cookies when — and only when — a cookie-enabled attempt fails with `Requested format is not available`. The cookie-less client path is the proven-working one across ~30 real videos in this investigation; a successful anonymous download beats a failed authenticated one. The fallback is deliberately narrow: no cookies configured → no retry (identical retry would be pointless); any other error (e.g. a genuinely unavailable video) → no retry (no wasted second network attempt). A warning is logged whenever the fallback fires so the cookie-caused failure stays visible rather than silently masked. Three new regression tests (`backend/tests/test_ytdlp_cookies.py`) pin all three behaviors; suite 213 → 216 passing. Live-verified in the real container that the normal path is unregressed.
    - **Follow-on option, deliberately not taken now:** the "proper" authenticated fix would be installing yt-dlp's EJS remote solver components and/or a `bgutil-ytdlp-pot-provider` sidecar so the authed clients actually work, keeping logged-in benefits (age-restricted content). That's real new infrastructure with its own failure modes, and the concrete user-facing need (downloads succeed) is met by the fallback; revisit only if age-restricted content with cookies becomes a real requirement.

### Original assumptions log

Track anything the agent has to assume here so it can be reviewed and corrected rather than silently baked in:

- **Assumed:** Output formats supported = mp3, flac, m4a, opus, wav, ogg (same set as spotDL-GUI). Confirm if this should change.
- **Resolved:** Spotify integration dropped entirely (see Non-goals, Section 3). MusicBrainz is primary metadata, YouTube Music is fallback metadata + playlist source + audio source. No Premium account or developer app dependency anywhere in the stack.
- **Assumed:** No built-in scheduler for "watch artist for new releases" in v1 — flagged as a backlog item, not built now.
- **Open:** Exact logo asset — placeholder monogram until a real logo is supplied.
- **Open:** Whether genre tagging pulls from MusicBrainz's genre/tag data or is left blank when unavailable — needs a decision before Batch 3.

---

*End of specification.*
