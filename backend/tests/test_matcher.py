"""Audio-source matching tests (Section 7.3 steps 2-3) — fake YTM client."""
from app.downloader.matcher import find_audio_source
from app.resolver.schemas import MetadataSource, ResolvedTrack


def mb_track(duration=274, video_id=None):
    return ResolvedTrack(
        title="Give Life Back to Music",
        artist_name="Daft Punk",
        duration_seconds=duration,
        youtube_video_id=video_id,
        source=MetadataSource.musicbrainz if video_id is None else MetadataSource.youtube_music,
    )


def candidate(video_id, duration):
    return ResolvedTrack(
        title="Give Life Back to Music",
        artist_name="Daft Punk",
        duration_seconds=duration,
        youtube_video_id=video_id,
        source=MetadataSource.youtube_music,
    )


class FakeYT:
    def __init__(self, songs=None, videos=None):
        self.songs = songs or []
        self.videos = videos or []
        self.calls = []

    def search_songs(self, query, limit=10):
        self.calls.append(("songs", query))
        return self.songs

    def search_videos(self, query, limit=10):
        self.calls.append(("videos", query))
        return self.videos


def test_existing_video_id_used_directly():
    yt = FakeYT()
    match = find_audio_source(yt, mb_track(video_id="abc123"))
    assert match is not None
    assert match.video_id == "abc123"
    assert match.audio_source == "youtube-music"
    assert match.url == "https://music.youtube.com/watch?v=abc123"
    assert yt.calls == []                       # no search needed


def test_duration_tolerance_is_the_gate():
    yt = FakeYT(songs=[
        candidate("way_off", 200),              # 74s off — rejected
        candidate("close_enough", 271),         # 3s off — accepted
    ])
    match = find_audio_source(yt, mb_track(duration=274), tolerance_seconds=5)
    assert match is not None
    assert match.video_id == "close_enough"
    assert match.audio_source == "youtube-music"


def test_falls_back_to_plain_youtube_search():
    yt = FakeYT(
        songs=[candidate("wrong_length", 400)],
        videos=[candidate("video_match", 275)],
    )
    match = find_audio_source(yt, mb_track(duration=274))
    assert match is not None
    assert match.video_id == "video_match"
    assert match.audio_source == "youtube"
    assert match.url == "https://www.youtube.com/watch?v=video_match"
    assert [c[0] for c in yt.calls] == ["songs", "videos"]


def test_no_match_anywhere_returns_none():
    yt = FakeYT(songs=[candidate("off1", 100)], videos=[candidate("off2", 500)])
    assert find_audio_source(yt, mb_track(duration=274)) is None


def test_unknown_target_duration_trusts_top_result():
    yt = FakeYT(songs=[candidate("top", 999)])
    match = find_audio_source(yt, mb_track(duration=None))
    assert match is not None
    assert match.video_id == "top"


def test_candidate_without_duration_accepted():
    yt = FakeYT(songs=[candidate("no_dur", None)])
    match = find_audio_source(yt, mb_track(duration=274))
    assert match is not None
    assert match.video_id == "no_dur"
