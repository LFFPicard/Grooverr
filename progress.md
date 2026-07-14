# Grooverr — Progress Summary (Batches 1–9)

*Last updated: 2026-07-14*

## Where things stand

Backend, frontend, settings, and packaging are all built, tested, and verified
against real services. 161 backend tests pass, the frontend builds clean, and
every batch's Definition of Done was exercised live — real MusicBrainz lookups,
real YouTube Music downloads, real crash-recovery kill tests, a real containerized
end-to-end download through a genuine host bind mount. What remains is hardening
(Batch 10).

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

### Batch 6 — Dashboard + Search ✅

Live frontend against SSE, Sleeve Catalog design tokens applied per the
resolved mockup decision. End-to-end pipeline (search → add → watch it
download) verified in-browser.

### Batch 7 — Library, Album Detail, Playlists, full Queue ✅

`Playlist`/`PlaylistTrack` tables added (resolved decision 2). Library rebuilt
as a single virtualized grid shared by Albums/Playlists tabs. Playlists
generate M3U8 manifests rather than duplicating audio (Section 6.1, resolved
2026-07-14). Added a mandatory duration cross-check to stop pre-existing
video-id mismatches from silently attaching the wrong audio.

### Batch 8 — Settings screen + credential handling ✅

MusicBrainz user-agent, YouTube cookie upload, default quality ceiling, and
output path template (with live preview) all wired to a real Settings API and
persisted in `/config`. M3U8 paths made relative and the playlist output
folder made configurable.

### Batch 9 — Packaging & Unraid template ✅

Multi-stage Dockerfile (Node build stage discarded, only `dist/` copied into
the final Python image), non-root by default via a PUID/PGID-aware
`entrypoint.sh` (`setpriv`, LinuxServer.io/Unraid convention), `tini` as PID 1,
`/api/health` HEALTHCHECK. `docker-compose.yml`, an Unraid CA template
(`unraid/grooverr.xml`), a GitHub Actions workflow to build/push to Docker Hub
on push to `main`, and a README.

Verified live: a real image build (zero warnings), a real container boot with
a genuine host-directory bind mount (not Docker's anonymous-volume fallback),
confirmed non-root execution and correct PUID/PGID remapping via the actual
process tree, and a real search → add → download through the container's API
landing correctly on the host at the right path with correct in-container
ownership. Not independently verified: a literal Unraid host, and a real
GitHub Actions run (see Section 11 of grooverr.md for the full list of what
was and wasn't verified and why).

## Decisions resolved along the way

- **The dashboard mockup** — added to the repo (`design/dashboard-reference.html`);
  Batch 6 built against it directly.
- **Playlists had no data model** — resolved: `Playlist`/`PlaylistTrack` tables
  added in Batch 7. Further resolved in Section 6.1 (2026-07-14): playlists
  generate an M3U8 manifest rather than duplicating audio files, with a
  configurable, relative-path output folder (Batch 8).
- **"Add artist" scope** — row-only for v1 stands; full discography
  pulling/monitoring remains an explicitly deferred v2 feature (Non-goals,
  Section 3).

## Still open (no decision needed yet, flagged for awareness)

- **Cover-art "mandatory" vs. unfetchable** — Section 6 says embedded art is
  mandatory, but Cover Art Archive images are sometimes missing. Current
  behaviour: the download succeeds with a logged warning and no art. Revisit
  if this needs to become a hard failure instead.

## Smaller items (awareness, no decision needed)

- Free-text search takes ~2–4s due to MusicBrainz's 1 req/s policy — fine for
  submit-based search, rules out search-as-you-type in the UI.
- Pre-CD-era tracks resolved *without album context* can carry the first CD
  pressing's year rather than the original vinyl year (fixable later via
  release-group `first-release-date`).
- Changing worker concurrency requires an app restart until the Batch 8 settings
  UI wires a pool resize.
- The output path template is simple `{Token}` substitution rather than full
  Jinja — still true, not revisited; no conditional-template need has come up.
- YouTube data downloads can transiently 403; manual retry works today, auto-retry
  with backoff is a Batch 10 hardening item.
- Final Docker image is ~955MB, ~461MB of which is the ffmpeg/tini/curl apt layer.
  Not pursued further — see grooverr.md Section 11 for the reasoning.

## Recommended order from here

Batch 10 (hardening): auto-retry with backoff for transient YouTube 403s, and
whatever else the spec's Section 10 hardening scope calls for. Batch 9's Docker
image was verified locally (real build, real bind-mounted container, real
end-to-end download) but not against a literal Unraid host or a real GitHub
Actions run — worth a first real deploy to close that loop before declaring v1
done.
