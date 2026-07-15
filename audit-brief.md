# Grooverr — Full Audit Brief

**Context:** All 10 batches of grooverr.md are implemented and individually
verified. This audit is a fresh, whole-system pass — not a re-check of
work already confirmed batch-by-batch, but a look for problems that only
show up when every piece is viewed together, and for anything that slipped
through despite the batch-level rigor.

**Read grooverr.md in full first**, particularly Section 11's resolution
log — it's a record of every real bug found during this build, and several
of them share a common shape. Use that shape to hunt for siblings.

---

## Priority 1 — Known bug classes, check for recurrences

This project has hit the same *kind* of mistake multiple times, in
different code. Specifically search for:

1. **Unsafe external-data access.** The original spotDL-GUI build died
   repeatedly to `KeyError` from unguarded dict indexing on API responses
   (`data["genres"]` instead of `data.get("genres")`). Grooverr's
   MusicBrainz/YouTube Music clients were built with this lesson in mind
   from Batch 2 onward — confirm that discipline actually held across
   *every* external API touchpoint added since, including the newer
   Artist Detail discography browse and anything Batch 10 added. Grep
   for direct bracket indexing on any variable that originated from an
   external API response or DB row.

2. **Scalar vs. tuple confusion in SQLModel/SQLAlchemy.** Batch 8 found a
   real bug where `session.exec()` returns bare scalars for single-column
   selects, and `row[0]` was silently slicing a string instead of
   indexing a tuple — two same-named playlists collided undetected. The
   codebase was audited once for this pattern; confirm nothing new
   introduced it since, especially in Batch 10's new concurrency/load
   test code.

3. **Trusting cached/pre-existing identifiers without re-validation.**
   Batch 6 found that a `Track` with a pre-existing `youtube_video_id`
   skipped duration cross-checking entirely — a silent audio mismatch
   with no error anywhere. The fix was making that check unconditional.
   Look for other places in the pipeline where a previously-resolved
   value is trusted on a second pass without being re-verified.

4. **Rate limiter fragmentation.** Confirmed unified as of Batch 10, but
   worth a fresh look given how easy it would be for a future code path
   to accidentally instantiate its own limiter instead of reusing the
   shared one. Grep for anywhere MusicBrainz is called and confirm it
   traces back to the single `app.runtime.resolver.mb` instance.

5. **Format-selector rigidity.** The yt-dlp "Requested format is not
   available" bug (round 2) came from over-constraining format selection
   at the wrong pipeline stage. Confirm the fix (broad selection, ceiling
   enforced only at ffmpeg transcode) is the *only* place quality
   constraints are applied — check there's no second, forgotten
   constraint elsewhere (e.g. in the YouTube Music search/matching step
   itself, not just the download step).

---

## Priority 2 — Cross-batch integration

Individual batches were verified in isolation. Check the seams:

- **Playlist M3U8 regeneration under real load.** Batch 4's queue system
  and Section 6.1's M3U8 regeneration both fire off "track finished
  downloading" — confirm they don't race each other or double-fire under
  the kind of real concurrency Batch 10's load test exercised (55
  concurrent albums). Does a playlist spanning multiple concurrently-
  downloading albums regenerate correctly, or could it write a
  half-complete M3U8 mid-burst?
- **Settings changes taking effect without a restart.** The playlist
  output folder and MusicBrainz user-agent are both Settings-configurable
  as of Batch 8 — confirm changing them actually takes effect on the
  *next* relevant action, not just on container restart.
- **Artist Detail's bulk "Add entire discography" interacting with the
  queue at scale.** A prolific artist (Linkin Park's 219 releases came up
  during testing) could enqueue hundreds of jobs at once from a single
  click. Does this behave the same as Batch 10's 55-concurrent-album load
  test, or is bulk-add a different code path that hasn't been load-tested
  specifically?

---

## Priority 3 — Spec compliance sweep

Go through grooverr.md section by section and confirm the implementation
actually matches what's written — not "close enough," literally matches.
Pay particular attention to:

- Section 6's file naming convention — test against real edge cases:
  multi-disc albums, artists with slashes/colons in their name (the AC/DC
  case was tested in Batch 3 — check for other similarly awkward real
  artist names), extremely long titles against `max_filename_length`.
- Section 9's performance requirements — Batch 10 benchmarked against a
  2,000-album seeded dataset. Is that dataset realistic in *shape* (long
  tail of small artists vs. a few huge ones), or uniform in a way that
  might hide a performance cliff a real library would hit?
- Section 3's non-goals — confirm none of them have quietly crept back in
  as accidental scope (e.g. does anything resemble automatic artist
  monitoring, even partially?).

---

## Priority 4 — Security & operational basics

- Are Settings credentials (none currently required, since Spotify was
  dropped — but the YouTube cookie file is sensitive) ever logged,
  echoed in an error message, or otherwise exposed anywhere they
  shouldn't be?
- Does the `/config` vs `/music` volume separation (Section on Unraid
  packaging) actually hold — could anything end up writing sensitive
  data into the music share by mistake?
- Container runs as non-root with PUID/PGID remapping per Batch 9 — spot
  check that this is actually enforced, not just configured.

---

## What "done" looks like for this audit

A list of findings, each tagged:
- **Confirmed clean** — checked, no issue
- **Found, fixed** — real bug, fixed and verified same as every batch
  before this (don't just patch it, prove it)
- **Found, flagged for decision** — something that needs a call from
  Gary before fixing (scope question, tradeoff, etc.)

Same standard as the whole build: findings are backed by actually running
something, not by code review alone where a live test is possible.
