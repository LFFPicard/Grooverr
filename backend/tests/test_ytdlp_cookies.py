"""
YouTube cookie file wiring tests (Batch 8). resolve_cookies_path() and the
cookiefile option-passing in download_audio — no real yt-dlp network calls.
"""
from unittest.mock import patch

from app.downloader.ytdlp import resolve_cookies_path, youtube_cookies_path


def test_resolve_cookies_path_none_when_not_uploaded(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    assert resolve_cookies_path() is None


def test_resolve_cookies_path_returns_file_when_present(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    cookie_file = youtube_cookies_path()
    cookie_file.write_text("# Netscape HTTP Cookie File\n")
    assert resolve_cookies_path() == str(cookie_file)


def test_download_audio_passes_cookiefile_when_present(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    cookie_file = youtube_cookies_path()
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    cookie_file.write_text("# Netscape HTTP Cookie File\n")

    captured = {}

    class FakeYDL:
        def __init__(self, options):
            captured["options"] = options
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def download(self, urls):
            (tmp_path / "vid123.mp3").write_bytes(b"fake audio")

    with patch("app.downloader.ytdlp.yt_dlp.YoutubeDL", FakeYDL):
        from app.downloader.ytdlp import download_audio
        download_audio("vid123", tmp_path, "mp3", ffmpeg_path="/fake/ffmpeg")

    assert captured["options"]["cookiefile"] == str(cookie_file)


def test_download_audio_omits_cookiefile_when_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "empty-config"))
    captured = {}

    class FakeYDL:
        def __init__(self, options):
            captured["options"] = options
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def download(self, urls):
            (tmp_path / "vid123.mp3").write_bytes(b"fake audio")

    with patch("app.downloader.ytdlp.yt_dlp.YoutubeDL", FakeYDL):
        from app.downloader.ytdlp import download_audio
        download_audio("vid123", tmp_path, "mp3", ffmpeg_path="/fake/ffmpeg")

    assert "cookiefile" not in captured["options"]


def test_download_audio_explicit_none_forces_no_cookies(tmp_path, monkeypatch):
    """Explicit None overrides even an uploaded cookie file."""
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    cookie_file = youtube_cookies_path()
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    cookie_file.write_text("# Netscape HTTP Cookie File\n")

    captured = {}

    class FakeYDL:
        def __init__(self, options):
            captured["options"] = options
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def download(self, urls):
            (tmp_path / "vid123.mp3").write_bytes(b"fake audio")

    with patch("app.downloader.ytdlp.yt_dlp.YoutubeDL", FakeYDL):
        from app.downloader.ytdlp import download_audio
        download_audio("vid123", tmp_path, "mp3", ffmpeg_path="/fake/ffmpeg", cookies_path=None)

    assert "cookiefile" not in captured["options"]
