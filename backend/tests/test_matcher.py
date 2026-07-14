"""
Audio-source matching tests (Section 7.3 steps 2-3) — fake YTM client.

Section 7.3 (decision resolved 2026-07-13): a pre-existing youtube_video_id
must never be trusted blindly — its actual duration is fetched and cross-
checked with the same tolerance as a fresh search match before use.
"""
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
    def __init__(self, songs=None, videos=None, get_track_result="unset", get_track_raises=False):
        self.songs = songs or []
        self.videos = videos or []
        self.calls = []
        self._get_track_result = get_track_result
        self._get_track_raises = get_track_raises

    def search_songs(self, query, limit=10):
        self.calls.append(("songs", query))
        return self.songs

    def search_videos(self, query, limit=10):
        self.calls.append(("videos", query))
        return self.videos

    def get_track(self, video_id):
        self.calls.append(("get_track", video_id))
        if self._get_track_raises:
            raise ConnectionError("YouTube Music is down")
        if self._get_track_result == "unset":
            raise AssertionError("get_track called but no result configured")
        return self._get_track_result


# ── Pre-existing video id: mandatory cross-check ────────────────────────────

def test_existing_video_id_verified_and_used_when_duration_matches():
    yt = FakeYT(get_track_result=candidate("abc123", 274))
    match = find_audio_source(yt, mb_track(duration=274, video_id="abc123"))
    assert match is not None
    assert match.video_id == "abc123"
    assert match.audio_source == "youtube-music"
    assert match.url == "https://music.youtube.com/watch?v=abc123"
    assert yt.calls == [("get_track", "abc123")]     # cross-checked, no search needed


def test_existing_video_id_within_tolerance_used():
    yt = FakeYT(get_track_result=candidate("abc123", 271))   # 3s off, tolerance 5
    match = find_audio_source(yt, mb_track(duration=274, video_id="abc123"))
    assert match is not None
    assert match.video_id == "abc123"


def test_existing_video_id_no_target_duration_still_trusted():
    """Leniency preserved: with no Track.duration_seconds to check against,
    a successfully-verified candidate is trusted (matches the free-search
    'no target duration' rule) — this is NOT a bypass, get_track is still
    called and must return something real."""
    yt = FakeYT(get_track_result=candidate("abc123", 999))
    match = find_audio_source(yt, mb_track(duration=None, video_id="abc123"))
    assert match is not None
    assert match.video_id == "abc123"
    assert yt.calls == [("get_track", "abc123")]


def test_existing_video_id_mismatch_falls_back_to_search():
    yt = FakeYT(
        get_track_result=candidate("stale123", 50),    # way off from 274
        songs=[candidate("freshmatch", 275)],
    )
    match = find_audio_source(yt, mb_track(duration=274, video_id="stale123"))
    assert match is not None
    assert match.video_id == "freshmatch"               # NOT the stale id
    assert ("get_track", "stale123") in yt.calls
    assert ("songs", "Give Life Back to Music Daft Punk") in yt.calls


def test_existing_video_id_lookup_failure_falls_back_to_search():
    yt = FakeYT(get_track_raises=True, songs=[candidate("freshmatch", 274)])
    match = find_audio_source(yt, mb_track(duration=274, video_id="stale123"))
    assert match is not None
    assert match.video_id == "freshmatch"


def test_existing_video_id_empty_lookup_falls_back_to_search():
    yt = FakeYT(get_track_result=None, songs=[candidate("freshmatch", 274)])
    match = find_audio_source(yt, mb_track(duration=274, video_id="stale123"))
    assert match is not None
    assert match.video_id == "freshmatch"


def test_existing_video_id_mismatch_and_no_fallback_match_returns_none():
    yt = FakeYT(get_track_result=candidate("stale123", 50))   # mismatch, no search hits
    assert find_audio_source(yt, mb_track(duration=274, video_id="stale123")) is None


# ── Free-text search path (no pre-existing video id) ────────────────────────

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
