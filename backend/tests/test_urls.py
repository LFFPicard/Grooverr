"""URL detection tests — pure parsing, no network."""
from app.resolver.urls import UrlType, parse_music_url


def test_ytm_track_url():
    parsed = parse_music_url("https://music.youtube.com/watch?v=sVCUCLjIBPU")
    assert parsed is not None
    assert parsed.url_type == UrlType.track
    assert parsed.id == "sVCUCLjIBPU"
    assert parsed.is_music_domain


def test_ytm_track_url_with_album_list_param_is_still_a_track():
    parsed = parse_music_url(
        "https://music.youtube.com/watch?v=sVCUCLjIBPU&list=OLAK5uy_kkoncSyGgqO4pOKt5v9tPNZLd_L6ldPBQ"
    )
    assert parsed is not None
    assert parsed.url_type == UrlType.track
    assert parsed.id == "sVCUCLjIBPU"


def test_ytm_album_audio_playlist_url():
    parsed = parse_music_url(
        "https://music.youtube.com/playlist?list=OLAK5uy_kkoncSyGgqO4pOKt5v9tPNZLd_L6ldPBQ"
    )
    assert parsed is not None
    assert parsed.url_type == UrlType.album
    assert parsed.id.startswith("OLAK5uy_")


def test_ytm_album_browse_url():
    parsed = parse_music_url("https://music.youtube.com/browse/MPREb_hyGRB4KDKZAg")
    assert parsed is not None
    assert parsed.url_type == UrlType.album
    assert parsed.id == "MPREb_hyGRB4KDKZAg"


def test_ytm_playlist_url():
    parsed = parse_music_url(
        "https://music.youtube.com/playlist?list=RDCLAK5uy_kb7EBi6y3GrtJri4_ZH56Ms786DFEimbM"
    )
    assert parsed is not None
    assert parsed.url_type == UrlType.playlist


def test_ytm_playlist_url_vl_prefix_stripped():
    parsed = parse_music_url("https://music.youtube.com/playlist?list=VLPLabc123")
    assert parsed is not None
    assert parsed.url_type == UrlType.playlist
    assert parsed.id == "PLabc123"


def test_ytm_artist_channel_url():
    parsed = parse_music_url("https://music.youtube.com/channel/UCGnRLDGBF9o9pfeVEDVNu9w")
    assert parsed is not None
    assert parsed.url_type == UrlType.artist
    assert parsed.id == "UCGnRLDGBF9o9pfeVEDVNu9w"


def test_plain_youtube_watch_url_is_track_non_music_domain():
    parsed = parse_music_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert parsed is not None
    assert parsed.url_type == UrlType.track
    assert not parsed.is_music_domain


def test_youtu_be_short_url():
    parsed = parse_music_url("https://youtu.be/dQw4w9WgXcQ")
    assert parsed is not None
    assert parsed.url_type == UrlType.track
    assert parsed.id == "dQw4w9WgXcQ"


def test_unrelated_url_returns_none():
    assert parse_music_url("https://example.com/watch?v=abc") is None


def test_garbage_returns_none():
    assert parse_music_url("not a url at all") is None
    assert parse_music_url("") is None


def test_watch_without_video_id_returns_none():
    assert parse_music_url("https://music.youtube.com/watch") is None


def test_playlist_without_list_returns_none():
    assert parse_music_url("https://music.youtube.com/playlist") is None
