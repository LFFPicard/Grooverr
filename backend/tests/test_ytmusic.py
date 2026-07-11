"""
YouTube Music wrapper tests — a fake YTMusic object returns canned (and
deliberately degraded) payloads; no network. Proves parsing never raises
on missing/malformed fields.
"""
from app.resolver.ytmusic import YouTubeMusicClient, _parse_duration, _parse_track
from app.resolver.schemas import MetadataSource

SONG_RESULT = {
    "title": "Give Life Back to Music",
    "videoId": "vid123",
    "artists": [{"name": "Daft Punk", "id": "chan1"}],
    "album": {"name": "Random Access Memories", "id": "MPREb_abc"},
    "duration": "4:34",
    "duration_seconds": 274,
    "thumbnails": [{"url": "small.jpg"}, {"url": "large.jpg"}],
}


class FakeYTMusic:
    def __init__(self, **responses):
        self._responses = responses
        self.calls = []

    def __getattr__(self, name):
        def method(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self._responses.get(name)
        return method


def test_parse_duration():
    assert _parse_duration("3:14") == 194
    assert _parse_duration("1:02:03") == 3723
    assert _parse_duration(200) == 200
    assert _parse_duration("garbage") is None
    assert _parse_duration(None) is None
    assert _parse_duration("") is None


def test_search_songs():
    client = YouTubeMusicClient(ytmusic=FakeYTMusic(search=[SONG_RESULT]))
    tracks = client.search_songs("give life back to music daft punk")
    assert len(tracks) == 1
    track = tracks[0]
    assert track.source == MetadataSource.youtube_music
    assert track.youtube_video_id == "vid123"
    assert track.artist_name == "Daft Punk"
    assert track.album_title == "Random Access Memories"
    assert track.duration_seconds == 274
    assert track.cover_art_url == "large.jpg"    # largest thumbnail
    assert track.musicbrainz_id is None


def test_search_songs_survives_degraded_payloads():
    degraded = [
        {},                                   # empty item
        {"title": None, "artists": "nope"},   # wrong types
        "not-a-dict",                         # non-dict entry
        {"title": "OK", "album": "string-album", "duration": "1:00"},
    ]
    client = YouTubeMusicClient(ytmusic=FakeYTMusic(search=degraded))
    tracks = client.search_songs("x")
    assert len(tracks) == 3                   # non-dict dropped, rest parsed
    assert tracks[2].album_title == "string-album"
    assert tracks[2].duration_seconds == 60


def test_search_returning_none_yields_empty_list():
    client = YouTubeMusicClient(ytmusic=FakeYTMusic(search=None))
    assert client.search_songs("x") == []
    assert client.search_albums("x") == []
    assert client.search_artists("x") == []


def test_get_track_matches_seed_video():
    watch = {"tracks": [
        {"videoId": "other", "title": "Radio filler"},
        {"videoId": "vid123", "title": "Seed Song", "length": "3:00",
         "artists": [{"name": "Someone"}], "album": {"name": "An Album"}},
    ]}
    client = YouTubeMusicClient(ytmusic=FakeYTMusic(get_watch_playlist=watch))
    track = client.get_track("vid123")
    assert track is not None
    assert track.title == "Seed Song"
    assert track.duration_seconds == 180


def test_get_track_empty_watch_playlist():
    client = YouTubeMusicClient(ytmusic=FakeYTMusic(get_watch_playlist={}))
    assert client.get_track("vid123") is None


def test_get_album_from_browse_id():
    album_data = {
        "title": "Random Access Memories",
        "type": "Album",
        "year": "2013",
        "trackCount": 2,
        "audioPlaylistId": "OLAK5uy_xyz",
        "artists": [{"name": "Daft Punk"}],
        "thumbnails": [{"url": "cover.jpg"}],
        "tracks": [
            {"title": "Track One", "videoId": "v1", "duration": "4:34"},
            {"title": "Track Two", "videoId": "v2", "duration_seconds": 322},
        ],
    }
    fake = FakeYTMusic(get_album=album_data)
    client = YouTubeMusicClient(ytmusic=fake)
    album = client.get_album("MPREb_abc")
    assert album is not None
    assert album.title == "Random Access Memories"
    assert album.album_type == "album"
    assert album.release_year == 2013
    assert album.total_tracks == 2
    assert album.youtube_playlist_id == "OLAK5uy_xyz"
    assert [t.track_number for t in album.tracks] == [1, 2]
    assert album.tracks[0].album_title == "Random Access Memories"
    assert album.tracks[0].artist_name == "Daft Punk"
    assert album.tracks[1].duration_seconds == 322
    # Browse id used directly — no translation call needed
    assert ("get_album_browse_id",) not in [(c[0],) for c in fake.calls]


def test_get_album_from_audio_playlist_id_translates_first():
    fake = FakeYTMusic(get_album_browse_id="MPREb_abc", get_album={"title": "X", "tracks": []})
    client = YouTubeMusicClient(ytmusic=fake)
    album = client.get_album("OLAK5uy_something")
    assert album is not None
    assert fake.calls[0][0] == "get_album_browse_id"
    assert album.youtube_browse_id == "MPREb_abc"


def test_get_album_translation_failure_returns_none():
    client = YouTubeMusicClient(ytmusic=FakeYTMusic(get_album_browse_id=None))
    assert client.get_album("OLAK5uy_something") is None


def test_get_artist():
    client = YouTubeMusicClient(
        ytmusic=FakeYTMusic(get_artist={"name": "Daft Punk", "channelId": "chan1"})
    )
    artist = client.get_artist("chan1")
    assert artist is not None
    assert artist.name == "Daft Punk"
    assert artist.youtube_channel_id == "chan1"
    assert client.get_artist("x") is not None  # same canned response

    empty_client = YouTubeMusicClient(ytmusic=FakeYTMusic(get_artist={}))
    assert empty_client.get_artist("chan1") is None


def test_get_playlist():
    playlist_data = {
        "id": "PLxyz",
        "title": "Road Trip",
        "author": {"name": "Gary"},
        "trackCount": 2,
        "tracks": [SONG_RESULT, {"title": "Second", "videoId": "v2"}],
    }
    client = YouTubeMusicClient(ytmusic=FakeYTMusic(get_playlist=playlist_data))
    playlist = client.get_playlist("PLxyz")
    assert playlist is not None
    assert playlist.title == "Road Trip"
    assert playlist.author == "Gary"
    assert playlist.total_tracks == 2
    assert len(playlist.tracks) == 2
    assert playlist.tracks[0].youtube_video_id == "vid123"


def test_parse_track_handles_every_field_missing():
    track = _parse_track({})
    assert track.title == ""
    assert track.artist_name is None
    assert track.duration_seconds is None
    assert track.youtube_video_id is None
