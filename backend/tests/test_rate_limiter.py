"""
Batch 10 DoD gate (grooverr.md Section 10 / Section 11 item 11): MusicBrainz
rate limiting must be a single, global, shared instance — not one per
module/call-site — because MusicBrainz enforces ~1 req/sec on the combined
traffic from one client, not per code path.

Two things are verified here:
1. A structural regression test: the real app.main lifespan wiring hands the
   worker pipeline the exact same MusicBrainzClient instance used by every
   API route (app.runtime.resolver.mb), not a second independent one.
2. A concurrent behavioural test: an interactive search running at the same
   time as a multi-page discography browse (what "Add entire discography"
   does) never issues two combined MusicBrainz requests less than ~1s apart
   — proven by asserting on real, logged request timestamps, not just by
   inspecting object identity.
"""
import asyncio
import time

import httpx
from fastapi.testclient import TestClient

from app import runtime
from app.api import search as search_module
from app.main import app
from app.queue.pipeline import Pipeline
from app.resolver.musicbrainz import MusicBrainzClient

app_client = TestClient(app)


def test_production_wiring_shares_one_musicbrainz_client(monkeypatch):
    """Locks in app/main.py's lifespan: WorkerPool's Pipeline must be
    constructed with resolver=runtime.resolver (the same object search.py
    and the new Artist Detail endpoints read mb/yt from), not a bare
    Pipeline(queue) that would silently default to its own MetadataResolver
    — and therefore its own, independent MusicBrainzClient rate limiter."""
    captured = {}
    original_init = Pipeline.__init__

    def spy_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        captured["resolver"] = self.resolver

    monkeypatch.setattr(Pipeline, "__init__", spy_init)

    with TestClient(app) as tc:  # triggers the real lifespan startup/shutdown
        pass

    assert captured.get("resolver") is runtime.resolver
    assert captured["resolver"].mb is runtime.resolver.mb


class FakeYT:
    """Never hit real YouTube Music from this test — only MusicBrainz
    request timing is under test here."""
    def search_songs(self, q, limit=5):
        return []

    def search_albums(self, q, limit=5):
        return []

    def search_artists(self, q, limit=5):
        return []


async def test_concurrent_search_and_discography_browse_share_rate_limit(monkeypatch):
    """The scenario from the spec: fire an interactive search while a
    multi-album resolve job (Artist Detail's 'Add entire discography',
    which pages through browse_release_groups_by_artist) is mid-flight.
    Combined request timing across BOTH code paths must never drop below
    ~1s apart, because both go through the one shared client."""
    request_log: list[tuple[float, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_log.append((time.monotonic(), request.url.path))
        if request.url.path == "/ws/2/release-group":
            return httpx.Response(200, json={"release-groups": [], "release-group-count": 0})
        if request.url.path == "/ws/2/recording":
            # Non-empty so search() doesn't also fire a second (fallback)
            # MB request or a YT fallback — keeps the request count exact.
            return httpx.Response(
                200, json={"recordings": [{"id": "r1", "title": "T", "score": 100}]}
            )
        return httpx.Response(200, json={})

    mb_client = MusicBrainzClient(
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), headers={"User-Agent": "test"}
        ),
        rate_limit_seconds=1.0,  # the real production MusicBrainz policy
    )
    monkeypatch.setattr(runtime.resolver, "mb", mb_client)
    monkeypatch.setattr(runtime.resolver, "yt", FakeYT())

    async def interactive_search():
        await search_module.search(q="some track title", mode="title")

    async def bulk_discography_resolve():
        # Mirrors add_entire_discography's paging loop over
        # browse_release_groups_by_artist for a multi-album artist.
        for _ in range(3):
            await mb_client.browse_release_groups_by_artist("artist-mbid", limit=25, offset=0)

    start = time.monotonic()
    await asyncio.gather(interactive_search(), bulk_discography_resolve())
    elapsed = time.monotonic() - start
    await mb_client.close()

    request_log.sort(key=lambda entry: entry[0])
    print("\nConcurrent MusicBrainz request log (search + discography browse, shared client):")
    for t, path in request_log:
        print(f"  t+{t - start:.3f}s  {path}")
    gaps = [b - a for (a, _), (b, _) in zip(request_log, request_log[1:])]
    print(f"Gaps between consecutive requests: {[f'{g:.3f}s' for g in gaps]}")

    assert len(request_log) == 4  # 1 from the search path + 3 from the browse path
    assert all(gap >= 0.95 for gap in gaps), (
        f"Two MusicBrainz requests from different code paths fired {min(gaps):.3f}s apart "
        "— the shared rate limiter did not correctly serialize both"
    )
    assert elapsed >= 2.9  # 4 requests at ~1s spacing must take ~3s, not run in parallel


async def test_concurrent_search_and_worker_resolve_share_rate_limit(monkeypatch):
    """Batch 10's exact DoD scenario, distinct from the browse test above:
    an interactive search fired while a multi-track metadata_resolve job
    (Section 7.2's worker — Pipeline._resolve, which calls
    resolver.resolve_track exactly like this) is mid-flight for several
    tracks at once, e.g. from a playlist import. Uses MetadataResolver
    directly (the same object Pipeline._resolve calls through
    self.resolver.resolve_track), not the lower-level MusicBrainzClient, so
    this exercises the actual worker code path rather than a stand-in."""
    request_log: list[tuple[float, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_log.append((time.monotonic(), request.url.path))
        if request.url.path == "/ws/2/recording":
            return httpx.Response(
                200, json={"recordings": [{"id": "r1", "title": "T", "score": 100}]}
            )
        return httpx.Response(200, json={})

    mb_client = MusicBrainzClient(
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), headers={"User-Agent": "test"}
        ),
        rate_limit_seconds=1.0,
    )
    from app.resolver.engine import MetadataResolver

    resolver = MetadataResolver(musicbrainz=mb_client, ytmusic=FakeYT())
    monkeypatch.setattr(runtime.resolver, "mb", mb_client)
    monkeypatch.setattr(runtime.resolver, "yt", FakeYT())

    async def interactive_search():
        await search_module.search(q="some other track", mode="title")

    async def worker_resolve_job(track_title: str):
        # Mirrors Pipeline._resolve calling self.resolver.resolve_track for
        # one queued metadata_resolve job. Three of these running together
        # is what a multi-track playlist/album import looks like in the
        # worker pool (Section 9.3: concurrency limit 3).
        await resolver.resolve_track(track_title, artist="Some Artist")

    start = time.monotonic()
    await asyncio.gather(
        interactive_search(),
        worker_resolve_job("Track One"),
        worker_resolve_job("Track Two"),
        worker_resolve_job("Track Three"),
    )
    elapsed = time.monotonic() - start
    await mb_client.close()

    request_log.sort(key=lambda entry: entry[0])
    print("\nConcurrent MusicBrainz request log (search + 3 worker resolve jobs, shared client):")
    for t, path in request_log:
        print(f"  t+{t - start:.3f}s  {path}")
    gaps = [b - a for (a, _), (b, _) in zip(request_log, request_log[1:])]
    print(f"Gaps between consecutive requests: {[f'{g:.3f}s' for g in gaps]}")

    # search path fires 1 request; each worker resolve job fires 1 request
    # (only_official_studio hit is non-empty, so no second fallback pass).
    assert len(request_log) == 4
    assert all(gap >= 0.95 for gap in gaps), (
        f"A search request and a worker resolve-job request fired {min(gaps):.3f}s apart "
        "— the shared rate limiter did not correctly serialize the worker pipeline with search"
    )
    assert elapsed >= 2.9
