"""
Fallback-chain tests (Section 7.2): MusicBrainz → YouTube Music.
Fake clients — no network.
"""
from typing import Optional

from app.resolver.engine import MetadataResolver
from app.resolver.schemas import (
    MetadataSource,
    ResolvedArtist,
    ResolvedAlbum,
    ResolvedTrack,
    ResolvedPlaylist,
)

MB_RECORDING_HIT = {
    "id": "rec-1",
    "score": 100,
    "title": "Real Song",
    "artist-credit": [{"name": "Real Artist", "artist": {"id": "art-1", "name": "Real Artist"}}],
    "releases": [{"id": "rel-1", "title": "Real Album", "status": "Official"}],
}


class FakeMB:
    """Stands in for MusicBrainzClient; parse_* statics are reused from it."""
    def __init__(self, recordings=None, releases=None, artists=None, release_lookup=None,
                 raise_on_search=False):
        self.recordings = recordings or []
        self.releases = releases or []
        self.artists = artists or []
        self.release_lookup = release_lookup or {}
        self.raise_on_search = raise_on_search

    async def search_recordings(self, title, artist=None, album=None, limit=10):
        if self.raise_on_search:
            raise ConnectionError("MB is down")
        return self.recordings

    async def search_releases(self, title, artist=None, limit=10):
        if self.raise_on_search:
            raise ConnectionError("MB is down")
        return self.releases

    async def search_artists(self, name, limit=10):
        if self.raise_on_search:
            raise ConnectionError("MB is down")
        return self.artists

    async def get_release(self, mbid):
        return self.release_lookup

    async def close(self):
        pass

    from app.resolver.musicbrainz import MusicBrainzClient as _MB
    parse_recording_hit = staticmethod(_MB.parse_recording_hit)
    parse_release = staticmethod(_MB.parse_release)
    parse_artist_hit = staticmethod(_MB.parse_artist_hit)


def yt_track(title="YT Song") -> ResolvedTrack:
    return ResolvedTrack(title=title, youtube_video_id="v1", source=MetadataSource.youtube_music)


class FakeYT:
    def __init__(self, songs=None, albums=None, artists=None,
                 track=None, album=None, artist=None, playlist=None):
        self.songs = songs or []
        self.albums = albums or []
        self.artists = artists or []
        self.track, self.album, self.artist, self.playlist = track, album, artist, playlist
        self.calls = []

    def search_songs(self, query, limit=10):
        self.calls.append("search_songs")
        return self.songs

    def search_albums(self, query, limit=10):
        self.calls.append("search_albums")
        return self.albums

    def search_artists(self, query, limit=10):
        self.calls.append("search_artists")
        return self.artists

    def get_track(self, video_id):
        self.calls.append(f"get_track:{video_id}")
        return self.track

    def get_album(self, album_id):
        self.calls.append(f"get_album:{album_id}")
        return self.album

    def get_artist(self, channel_id):
        self.calls.append(f"get_artist:{channel_id}")
        return self.artist

    def get_playlist(self, playlist_id, limit=None):
        self.calls.append(f"get_playlist:{playlist_id}")
        return self.playlist


def make_resolver(mb: FakeMB, yt: Optional[FakeYT] = None) -> MetadataResolver:
    return MetadataResolver(musicbrainz=mb, ytmusic=yt or FakeYT())


# ── resolve_track ──────────────────────────────────────────────────────────

async def test_track_confident_mb_hit_wins():
    yt = FakeYT(songs=[yt_track()])
    resolver = make_resolver(FakeMB(recordings=[MB_RECORDING_HIT]), yt)
    track = await resolver.resolve_track("Real Song", artist="Real Artist")
    assert track is not None
    assert track.source == MetadataSource.musicbrainz
    assert track.musicbrainz_id == "rec-1"
    assert yt.calls == []                     # fallback never touched


async def test_track_low_score_falls_back_to_ytm():
    low = dict(MB_RECORDING_HIT, score=40)
    yt = FakeYT(songs=[yt_track()])
    resolver = make_resolver(FakeMB(recordings=[low]), yt)
    track = await resolver.resolve_track("Real Song")
    assert track is not None
    assert track.source == MetadataSource.youtube_music
    assert "search_songs" in yt.calls


async def test_track_no_mb_results_falls_back():
    yt = FakeYT(songs=[yt_track()])
    resolver = make_resolver(FakeMB(recordings=[]), yt)
    track = await resolver.resolve_track("Whatever")
    assert track is not None
    assert track.source == MetadataSource.youtube_music


async def test_track_mb_exception_falls_back():
    yt = FakeYT(songs=[yt_track()])
    resolver = make_resolver(FakeMB(raise_on_search=True), yt)
    track = await resolver.resolve_track("Whatever")
    assert track is not None
    assert track.source == MetadataSource.youtube_music


async def test_track_nothing_anywhere_returns_none():
    resolver = make_resolver(FakeMB(), FakeYT())
    assert await resolver.resolve_track("zzz gibberish zzz") is None


# ── resolve_album ──────────────────────────────────────────────────────────

async def test_album_confident_mb_hit_does_full_lookup():
    search_hit = {"id": "rel-1", "score": 100, "title": "Real Album"}
    lookup = {
        "id": "rel-1",
        "title": "Real Album",
        "media": [{"position": 1, "track-count": 1,
                   "tracks": [{"position": 1, "title": "T1", "recording": {"id": "rec-1"}}]}],
    }
    resolver = make_resolver(FakeMB(releases=[search_hit], release_lookup=lookup))
    album = await resolver.resolve_album("Real Album")
    assert album is not None
    assert album.source == MetadataSource.musicbrainz
    assert album.musicbrainz_id == "rel-1"
    assert len(album.tracks) == 1             # full lookup got the track list


async def test_album_fallback_pulls_full_ytm_album():
    summary = ResolvedAlbum(
        title="YT Album", youtube_browse_id="MPREb_x", source=MetadataSource.youtube_music
    )
    full = ResolvedAlbum(
        title="YT Album", youtube_browse_id="MPREb_x",
        tracks=[yt_track("T1")], source=MetadataSource.youtube_music,
    )
    yt = FakeYT(albums=[summary], album=full)
    resolver = make_resolver(FakeMB(), yt)
    album = await resolver.resolve_album("YT Album")
    assert album is not None
    assert len(album.tracks) == 1
    assert "get_album:MPREb_x" in yt.calls


# ── resolve_artist ─────────────────────────────────────────────────────────

async def test_artist_mb_then_fallback():
    resolver = make_resolver(
        FakeMB(artists=[{"id": "art-1", "score": 100, "name": "Real Artist"}])
    )
    artist = await resolver.resolve_artist("Real Artist")
    assert artist is not None
    assert artist.musicbrainz_id == "art-1"

    yt = FakeYT(artists=[ResolvedArtist(name="YT Artist", source=MetadataSource.youtube_music)])
    resolver = make_resolver(FakeMB(), yt)
    artist = await resolver.resolve_artist("YT Artist")
    assert artist is not None
    assert artist.source == MetadataSource.youtube_music


# ── resolve_url ────────────────────────────────────────────────────────────

async def test_resolve_url_dispatches_by_type():
    yt = FakeYT(
        track=yt_track(),
        album=ResolvedAlbum(title="A", source=MetadataSource.youtube_music),
        artist=ResolvedArtist(name="Ar", source=MetadataSource.youtube_music),
        playlist=ResolvedPlaylist(title="P", source=MetadataSource.youtube_music),
    )
    resolver = make_resolver(FakeMB(), yt)

    result = await resolver.resolve_url("https://music.youtube.com/watch?v=vid1")
    assert isinstance(result, ResolvedTrack)

    result = await resolver.resolve_url("https://music.youtube.com/playlist?list=OLAK5uy_x")
    assert isinstance(result, ResolvedAlbum)

    result = await resolver.resolve_url("https://music.youtube.com/channel/UCabc")
    assert isinstance(result, ResolvedArtist)

    result = await resolver.resolve_url("https://music.youtube.com/playlist?list=PLabc")
    assert isinstance(result, ResolvedPlaylist)

    assert yt.calls == [
        "get_track:vid1", "get_album:OLAK5uy_x", "get_artist:UCabc", "get_playlist:PLabc",
    ]


async def test_resolve_url_unrecognised_returns_none():
    resolver = make_resolver(FakeMB(), FakeYT())
    assert await resolver.resolve_url("https://example.com/nope") is None
