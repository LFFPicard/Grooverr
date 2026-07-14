"""
MusicBrainz client tests — httpx.MockTransport for request-level behaviour,
plus parser tests fed deliberately degraded payloads to prove that missing
or malformed fields never raise (the Batch 2 safe-access requirement).
"""
import json
import time

import httpx
import pytest

from app.resolver.musicbrainz import (
    MusicBrainzClient,
    cover_art_url,
    release_group_cover_art_url,
    _lucene_escape,
)
from app.resolver.schemas import MetadataSource

RECORDING_HIT = {
    "id": "rec-mbid-1",
    "score": 100,
    "title": "Give Life Back to Music",
    "length": 274000,
    "artist-credit": [
        {"name": "Daft Punk", "artist": {"id": "artist-mbid-1", "name": "Daft Punk"}}
    ],
    "releases": [
        {
            "id": "rel-mbid-nonofficial",
            "title": "Bootleg Comp",
            "status": "Bootleg",
            "release-group": {"primary-type": "Album"},
            "media": [{"position": 1, "track": [{"number": "3"}]}],
        },
        {
            "id": "rel-mbid-1",
            "title": "Random Access Memories",
            "status": "Official",
            "date": "2013-05-17",
            "release-group": {"primary-type": "Album"},
            "media": [{"position": 1, "track": [{"number": "1"}]}],
        },
    ],
}


def make_client(handler) -> MusicBrainzClient:
    transport = httpx.MockTransport(handler)
    return MusicBrainzClient(
        client=httpx.AsyncClient(
            transport=transport,
            headers={"User-Agent": "Grooverr-test/0.0"},
        ),
        rate_limit_seconds=0,
    )


async def test_search_recordings_parses_query_and_result():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["ua"] = request.headers.get("User-Agent")
        return httpx.Response(200, json={"recordings": [RECORDING_HIT]})

    client = make_client(handler)
    hits = await client.search_recordings(
        "Give Life Back to Music", artist="Daft Punk", album="Random Access Memories"
    )
    await client.close()

    assert len(hits) == 1
    assert 'recording%3A%22Give+Life+Back+to+Music%22' in seen["url"].replace("%20", "+")
    assert "fmt=json" in seen["url"]
    assert seen["ua"] == "Grooverr-test/0.0"


async def test_search_handles_missing_result_key():
    client = make_client(lambda req: httpx.Response(200, json={"count": 0}))
    assert await client.search_recordings("anything") == []
    await client.close()


async def test_http_error_raises():
    client = make_client(lambda req: httpx.Response(503, text="rate limited"))
    with pytest.raises(httpx.HTTPStatusError):
        await client.search_recordings("anything")
    await client.close()


async def test_rate_limiter_spaces_requests():
    client = make_client(lambda req: httpx.Response(200, json={"recordings": []}))
    client.rate_limit_seconds = 0.2
    start = time.monotonic()
    await client.search_recordings("one")
    await client.search_recordings("two")
    await client.search_recordings("three")
    elapsed = time.monotonic() - start
    await client.close()
    assert elapsed >= 0.4, f"3 requests at 0.2s spacing took only {elapsed:.3f}s"


def test_parse_recording_hit_prefers_official_release():
    track = MusicBrainzClient.parse_recording_hit(RECORDING_HIT)
    assert track.source == MetadataSource.musicbrainz
    assert track.musicbrainz_id == "rec-mbid-1"
    assert track.musicbrainz_release_id == "rel-mbid-1"       # official beats bootleg
    assert track.musicbrainz_artist_id == "artist-mbid-1"
    assert track.album_title == "Random Access Memories"
    assert track.track_number == 1
    assert track.disc_number == 1
    assert track.duration_seconds == 274
    assert track.release_year == 2013
    assert track.cover_art_url == cover_art_url("rel-mbid-1")


def test_parse_recording_hit_prefers_earliest_official_release():
    hit = {
        "id": "rec-1",
        "title": "T",
        "releases": [
            {"id": "reissue", "title": "Album", "status": "Official", "date": "2023-05-12",
             "release-group": {"primary-type": "Album"}},
            {"id": "original", "title": "Album", "status": "Official", "date": "2013-05-17",
             "release-group": {"primary-type": "Album"}},
        ],
    }
    track = MusicBrainzClient.parse_recording_hit(hit)
    assert track.musicbrainz_release_id == "original"
    assert track.release_year == 2013


def test_parse_recording_hit_prefers_cd_over_vinyl_and_offsets_vinyl_numbers():
    hit = {
        "id": "rec-1",
        "title": "T",
        "releases": [
            {"id": "vinyl", "title": "Album", "status": "Official", "date": "2013-10-28",
             "release-group": {"primary-type": "Album"},
             "media": [{"position": 2, "format": "12\" Vinyl", "track-offset": 5,
                        "track": [{"number": "D3", "title": "T"}]}]},
            {"id": "cd", "title": "Album", "status": "Official", "date": "2013-10-28",
             "release-group": {"primary-type": "Album"},
             "media": [{"position": 2, "format": "CD", "track": [{"number": "6"}]}]},
        ],
    }
    track = MusicBrainzClient.parse_recording_hit(hit)
    assert track.musicbrainz_release_id == "cd"
    assert track.track_number == 6

    # Vinyl-only recording: track number derived from the medium offset.
    vinyl_only = {"id": "rec-2", "title": "T", "releases": [hit["releases"][0]]}
    track = MusicBrainzClient.parse_recording_hit(vinyl_only)
    assert track.track_number == 6            # track-offset 5 → 6th track
    assert track.disc_number == 2


def test_parse_recording_hit_album_hint_overrides():
    track = MusicBrainzClient.parse_recording_hit(RECORDING_HIT, album_hint="bootleg comp")
    assert track.musicbrainz_release_id == "rel-mbid-nonofficial"


def test_album_artist_is_release_credit_not_track_credit():
    hit = {
        "id": "rec-1",
        "title": "Give Life Back to Music",
        "artist-credit": [
            {"name": "Daft Punk", "joinphrase": " feat. ",
             "artist": {"id": "artist-mbid-1", "name": "Daft Punk"}},
            {"name": "Nile Rodgers", "artist": {"id": "artist-mbid-2", "name": "Nile Rodgers"}},
        ],
        "releases": [
            {"id": "rel-1", "title": "Random Access Memories", "status": "Official",
             "date": "2013-05-17", "release-group": {"primary-type": "Album"},
             "artist-credit": [{"name": "Daft Punk", "artist": {"id": "artist-mbid-1"}}]},
        ],
    }
    track = MusicBrainzClient.parse_recording_hit(hit)
    assert track.artist_name == "Daft Punk feat. Nile Rodgers"
    assert track.album_artist == "Daft Punk"

    # Release without its own credit → primary (first) recording credit.
    hit["releases"][0].pop("artist-credit")
    track = MusicBrainzClient.parse_recording_hit(hit)
    assert track.album_artist == "Daft Punk"


def test_parse_recording_hit_survives_empty_payload():
    track = MusicBrainzClient.parse_recording_hit({})
    assert track.title == ""
    assert track.musicbrainz_id is None
    assert track.duration_seconds is None


def test_parse_recording_hit_survives_malformed_shapes():
    malformed = {
        "title": "X",
        "length": "not-a-number",
        "artist-credit": "not-a-list",
        "releases": [None, "string", {"media": "not-a-list"}],
    }
    track = MusicBrainzClient.parse_recording_hit(malformed)
    assert track.title == "X"
    assert track.duration_seconds is None
    assert track.artist_name is None


def test_parse_release_full_lookup():
    release = {
        "id": "rel-mbid-1",
        "title": "Random Access Memories",
        "date": "2013-05-17",
        "artist-credit": [
            {"name": "Daft Punk", "artist": {"id": "artist-mbid-1", "name": "Daft Punk"}}
        ],
        "release-group": {
            "primary-type": "Album",
            "secondary-types": [],
            "genres": [{"name": "disco", "count": 13}, {"name": "club", "count": 1}],
        },
        "genres": [{"name": "electronic", "count": 10}],
        "media": [
            {
                "position": 1,
                "track-count": 2,
                "tracks": [
                    {
                        "position": 1,
                        "title": "Give Life Back to Music",
                        "length": 274000,
                        "recording": {"id": "rec-mbid-1"},
                    },
                    {
                        "position": 2,
                        "title": "The Game of Love",
                        "recording": {"id": "rec-mbid-2", "length": 322000},
                    },
                ],
            }
        ],
    }
    album = MusicBrainzClient.parse_release(release)
    assert album.musicbrainz_id == "rel-mbid-1"
    assert album.album_type == "album"
    assert album.release_year == 2013
    assert album.total_tracks == 2
    assert album.genre == "electronic"
    assert len(album.tracks) == 2
    assert album.tracks[0].musicbrainz_id == "rec-mbid-1"
    assert album.tracks[0].track_number == 1
    assert album.tracks[1].duration_seconds == 322   # falls back to recording length


def test_genre_falls_back_to_release_group_votes():
    album = MusicBrainzClient.parse_release(
        {
            "id": "x",
            "title": "T",
            "genres": [],
            "release-group": {
                "primary-type": "Album",
                "genres": [{"name": "club", "count": 1}, {"name": "disco", "count": 13}],
            },
        }
    )
    assert album.genre == "disco"    # highest vote count, not first in list


def test_parse_release_compilation_type():
    album = MusicBrainzClient.parse_release(
        {
            "id": "x",
            "title": "Now 100",
            "release-group": {"primary-type": "Album", "secondary-types": ["Compilation"]},
        }
    )
    assert album.album_type == "compilation"


def test_parse_release_search_hit_without_track_lists():
    album = MusicBrainzClient.parse_release(
        {"id": "x", "title": "T", "track-count": 12}
    )
    assert album.total_tracks == 12
    assert album.tracks == []


def test_parse_artist_hit():
    artist = MusicBrainzClient.parse_artist_hit(
        {"id": "artist-mbid-1", "name": "Daft Punk", "sort-name": "Daft Punk"}
    )
    assert artist.musicbrainz_id == "artist-mbid-1"
    assert artist.source == MetadataSource.musicbrainz
    assert MusicBrainzClient.parse_artist_hit({}).name == ""


def test_lucene_escape():
    assert _lucene_escape('say "hello"') == 'say \\"hello\\"'
    assert _lucene_escape("back\\slash") == "back\\\\slash"


# ── Discography browse (Section 7.1.1) ──────────────────────────────────────

RELEASE_GROUP_HITS = [
    {
        "id": "rg-1",
        "title": "Hybrid Theory",
        "first-release-date": "2000-10-24",
        "primary-type": "Album",
    },
    {
        "id": "rg-2",
        "title": "One Step Closer",
        "first-release-date": "2000-02-01",
        "primary-type": "Single",
    },
]

RG_1_RELEASES = [
    {"id": "rel-reissue", "title": "Hybrid Theory", "status": "Official", "date": "2020-10-24"},
    {"id": "rel-original", "title": "Hybrid Theory", "status": "Official", "date": "2000-10-24"},
]


async def test_browse_release_groups_by_artist_queries_by_mbid_not_text():
    """Deliberately does NOT request inc=releases — verified live against
    the real MusicBrainz API that it 400s on this browse resource even
    though it's valid on a release-group lookup; a mocked-transport test
    alone wouldn't have caught that, so this also pins the exact params."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200, json={"release-groups": RELEASE_GROUP_HITS, "release-group-count": 2}
        )

    client = make_client(handler)
    groups, total = await client.browse_release_groups_by_artist("artist-mbid-lp", limit=25, offset=0)
    await client.close()

    assert seen["params"]["artist"] == "artist-mbid-lp"
    assert "inc" not in seen["params"]
    assert "query" not in seen["params"]  # structured browse, never a text search
    assert total == 2
    assert len(groups) == 2


async def test_browse_release_groups_handles_missing_keys():
    client = make_client(lambda req: httpx.Response(200, json={}))
    groups, total = await client.browse_release_groups_by_artist("artist-mbid")
    await client.close()
    assert groups == []
    assert total == 0


async def test_browse_releases_by_release_group_queries_by_mbid():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"releases": RG_1_RELEASES})

    client = make_client(handler)
    releases = await client.browse_releases_by_release_group("rg-1")
    await client.close()

    assert seen["params"]["release-group"] == "rg-1"
    assert "query" not in seen["params"]
    assert len(releases) == 2


async def test_browse_releases_by_release_group_handles_missing_keys():
    client = make_client(lambda req: httpx.Response(200, json={}))
    assert await client.browse_releases_by_release_group("rg-x") == []
    await client.close()


def test_parse_release_group_browse_hit_carries_release_group_id_not_a_release():
    """No release id is resolved at browse time (MusicBrainz can't embed
    member releases on this resource) — musicbrainz_id stays unset and
    release_group_id carries the id instead, resolved lazily at add-time."""
    album = MusicBrainzClient.parse_release_group_browse_hit(
        RELEASE_GROUP_HITS[0], artist_name="Linkin Park", artist_mbid="artist-mbid-lp"
    )
    assert album.title == "Hybrid Theory"
    assert album.artist_name == "Linkin Park"
    assert album.musicbrainz_artist_id == "artist-mbid-lp"
    assert album.musicbrainz_id is None
    assert album.release_group_id == "rg-1"
    assert album.release_year == 2000
    assert album.album_type == "album"
    assert album.cover_art_url == release_group_cover_art_url("rg-1")
    assert album.total_tracks is None                    # filled in later by get_release()


def test_release_rank_picks_earliest_official_release_among_release_group_members():
    """The lazy add-time resolution (app.api.library._resolve_full_album)
    ranks browse_releases_by_release_group's output with this same
    _release_rank helper — proven directly here against realistic bare
    release stubs (no nested release-group/media, unlike a recording hit's
    releases)."""
    from app.resolver.musicbrainz import _release_rank

    best = max(RG_1_RELEASES, key=_release_rank)
    assert best["id"] == "rel-original"


def test_parse_release_group_browse_hit_survives_no_releases():
    album = MusicBrainzClient.parse_release_group_browse_hit({"id": "rg-x", "title": "Unreleased"})
    assert album.title == "Unreleased"
    assert album.musicbrainz_id is None


async def test_search_freetext_strips_lucene_operators():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["query"] = dict(request.url.params).get("query")
        return httpx.Response(200, json={"recordings": [RECORDING_HIT]})

    client = make_client(handler)
    hits = await client.search_freetext("recording", 'AC/DC: "T.N.T." (live?)')
    await client.close()
    assert len(hits) == 1
    assert seen["query"] == "AC DC T.N.T. live"

    empty_client = make_client(handler)
    assert await empty_client.search_freetext("recording", ":::") == []
    await empty_client.close()
