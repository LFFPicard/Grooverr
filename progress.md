# Grooverr — Progress Summary (Batches 1–5)

*Last updated: 2026-07-12*

## Where things stand

The entire backend is built, tested, and verified against real services. 117 tests
pass, the working tree is clean, and every batch's Definition of Done was exercised
live — real MusicBrainz lookups, real YouTube Music downloads, real crash-recovery
kill tests. What remains is the frontend (Batches 6–7), settings UI (8), packaging
(9), and hardening (10).

## Batch-by-batch

### Batch 1 — Scaffolding ✅

FastAPI backend, WAL-mode SQLite with the full Section 5 schema, React+Vite+Tailwind
frontend with Sleeve Catalog design tokens, single-container Docker build.

### Batch 2 — Metadata resolution engine ✅

MusicBrainz REST client (1 req/s rate limiter, proper user-agent), YouTube Music
wrapper (`ytmusicapi`), URL type detection for all four YTM link shapes, and the
MB→YTM fallback chain. Zero unsafe dict indexing, verified by grep and
malformed-payload tests.

The hard-won piece: **MusicBrainz's relevance score is not canonicality** —
remasters and bootlegs outscore originals — so resolution ranks by *release
canonicality* (exact title > official > album-type > CD/digital pressing >
earliest date) with exact-match admission below the score threshold, and a
studio-first two-pass search (`status:official AND primarytype:album AND NOT
secondarytype:live`, retrying unconstrained).

### Batch 3 — Download & tagging engine ✅

yt-dlp download with per-job quality ceiling, ffmpeg conversion to all six output
formats (mp3/flac/m4a/opus/wav/ogg), mutagen tagging with Picard's exact
per-container MBID mappings, embedded cover art, and the Section 6 path convention
(conditional disc prefix, zero-padded track numbers, illegal-character
sanitization).

Verified by real downloads inspected on disk, including a multi-disc FLAC
(`Arcade Fire/Reflektor (2013)/2-06 - Supersymmetry.flac`) and an AC/DC
illegal-characters case (folder `AC-DC`, tags keep "AC/DC"). Fixed along the way:
album-artist must come from the release credit, not the track credit ("Daft Punk
feat. Nile Rodgers" must not become a library folder).

### Batch 4 — Queue system & background workers ✅

Persisted job queue in SQLite, asyncio worker pool (event-signalled with 5s poll
fallback, no busy-loop, configurable concurrency, default 3), SSE endpoint with
live per-percent download progress, startup recovery of stuck jobs.

Verified live: API-driven add → resolved → downloaded → placed with zero
intervention; process hard-killed mid-job twice (resolve stage and download stage)
and recovered within seconds on restart. Found and fixed a duplicate-download bug
in the crash path (`enqueue_download` is now idempotent per track).

### Batch 5 — Core REST API layer ✅

15 OpenAPI-documented endpoints: search (URL + free-text with token-similarity
re-ranking), add-to-library (track/album/artist/playlist), paginated library grid
(single aggregated query, no N+1), album detail, artist listing, queue
listing/retry/cancel, settings CRUD with per-key validation, dashboard stats.

Verified at scale: 1,500 albums / 15,000 tracks seeded — every library page under
50 ms, index usage confirmed via `EXPLAIN QUERY PLAN` (a 1,200-album scale test
lives in the suite so it can't regress). Fixed: one-box "title artist" queries
couldn't match MB's phrase-quoted search (added unfielded freetext search); MB
relevance ranked mashups first (Jaccard token re-ranking, earliest-release
tie-break); and "best quality" silently produced 128 kbps mp3s (now ~276 kbps VBR
q0 for mp3/ogg, 192k m4a, stream-copy for opus).

## Decisions required before continuing

All of these are also flagged in the grooverr.md Section 11 assumptions log.

### 1. The Batch 6 blocker: the dashboard mockup ⛔

The spec says to build the Dashboard "exactly per the confirmed mockup (Style B /
Sleeve Catalog)… use it as the literal starting point, do not redesign from
scratch" — but that mockup is not in the repo. **Needed: the mockup (image or
HTML), or explicit permission to design from the Section 8 written spec alone.**

### 2. Playlists have no data model

Section 7.4 promises "Complete this playlist," but Section 5 defines no Playlist
table, so there is nothing to group playlist tracks by — adds currently enqueue
each track individually and the grouping is lost. **Decide before Batch 7:** add
`Playlist`/`PlaylistTrack` tables (recommended — a small additive migration), or
drop playlist completeness for v1.

### 3. Cover-art "mandatory" vs. unfetchable

Section 6 says embedded art is mandatory on every file, but Cover Art Archive
images are sometimes missing. Current behaviour: the download succeeds with a
logged warning and no art. **Confirm this is acceptable**, or missing art should
fail the download instead.

### 4. "Add artist" scope

Adding an artist from search currently creates the artist row only. Lidarr-style
discography pulling/monitoring is a much bigger feature that the Non-goals section
appears to defer to v2. **Confirm row-only is acceptable for v1.**

## Smaller items (awareness, no decision needed)

- Free-text search takes ~2–4s due to MusicBrainz's 1 req/s policy — fine for
  submit-based search, rules out search-as-you-type in the UI.
- Pre-CD-era tracks resolved *without album context* can carry the first CD
  pressing's year rather than the original vinyl year (fixable later via
  release-group `first-release-date`).
- Changing worker concurrency requires an app restart until the Batch 8 settings
  UI wires a pool resize.
- The output path template is simple `{Token}` substitution rather than full
  Jinja — revisit at Batch 8 if conditional templates are wanted.
- YouTube data downloads can transiently 403; manual retry works today, auto-retry
  with backoff is a Batch 10 hardening item.

## Recommended order from here

Resolve decision 1 → build Batch 6 (Dashboard + Search — the first batch where the
whole system runs end-to-end through a UI) → decide 2 before Batch 7.
