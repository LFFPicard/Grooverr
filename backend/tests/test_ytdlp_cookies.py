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
        def download(self, urls):
            (tmp_path / "vid123.mp3").write_bytes(b"fake audio")
        def close(self):
            pass

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
        def download(self, urls):
            (tmp_path / "vid123.mp3").write_bytes(b"fake audio")
        def close(self):
            pass

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
        def download(self, urls):
            (tmp_path / "vid123.mp3").write_bytes(b"fake audio")
        def close(self):
            pass

    with patch("app.downloader.ytdlp.yt_dlp.YoutubeDL", FakeYDL):
        from app.downloader.ytdlp import download_audio
        download_audio("vid123", tmp_path, "mp3", ffmpeg_path="/fake/ffmpeg", cookies_path=None)

    assert "cookiefile" not in captured["options"]


def test_cookiejar_close_failure_does_not_fail_an_already_successful_download(tmp_path, monkeypatch):
    """Section 11 item 20: yt-dlp unconditionally tries to persist rotated
    cookies back to the cookiefile on close. Live-reproduced on a real
    permission-mismatched /config volume: the download itself completed
    (audio fetched + converted) but a raw, uncaught exception from that
    close()-time write-back discarded the whole job anyway. A cleanup
    failure must never discard a download that already succeeded."""
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    cookie_file = youtube_cookies_path()
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    cookie_file.write_text("# Netscape HTTP Cookie File\n")

    class FakeYDL:
        def __init__(self, options):
            pass
        def download(self, urls):
            (tmp_path / "vid123.mp3").write_bytes(b"fake audio")
        def close(self):
            raise PermissionError(13, "Permission denied", str(cookie_file))

    with patch("app.downloader.ytdlp.yt_dlp.YoutubeDL", FakeYDL):
        from app.downloader.ytdlp import download_audio
        result = download_audio("vid123", tmp_path, "mp3", ffmpeg_path="/fake/ffmpeg")

    assert result == tmp_path / "vid123.mp3"
    assert result.is_file()


def test_format_unavailable_with_cookies_retries_once_without_cookies(tmp_path, monkeypatch):
    """Section 11 item 21: valid account cookies flip yt-dlp onto its
    authenticated client list (tv_downgraded/web_safari), both currently
    format-gated — yielding 'Requested format is not available' on every
    video while the identical cookie-less call succeeds via android_vr.
    The wrapper must retry once without cookies rather than failing."""
    import yt_dlp
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    cookie_file = youtube_cookies_path()
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    cookie_file.write_text("# Netscape HTTP Cookie File\n")

    attempts = []

    class FakeYDL:
        def __init__(self, options):
            self.options = options
        def download(self, urls):
            attempts.append("with-cookies" if "cookiefile" in self.options else "no-cookies")
            if "cookiefile" in self.options:
                raise yt_dlp.utils.DownloadError(
                    "ERROR: [youtube] vid123: Requested format is not available. "
                    "Use --list-formats for a list of available formats"
                )
            (tmp_path / "vid123.mp3").write_bytes(b"fake audio")
        def close(self):
            pass

    with patch("app.downloader.ytdlp.yt_dlp.YoutubeDL", FakeYDL):
        from app.downloader.ytdlp import download_audio
        result = download_audio("vid123", tmp_path, "mp3", ffmpeg_path="/fake/ffmpeg")

    assert attempts == ["with-cookies", "no-cookies"]
    assert result.is_file()


def test_format_unavailable_without_cookies_does_not_retry(tmp_path, monkeypatch):
    """No cookies in play → the fallback doesn't apply; the error must
    surface immediately (retrying identically would be pointless)."""
    import yt_dlp
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "empty-config"))

    attempts = []

    class FakeYDL:
        def __init__(self, options):
            self.options = options
        def download(self, urls):
            attempts.append(1)
            raise yt_dlp.utils.DownloadError(
                "ERROR: [youtube] vid123: Requested format is not available."
            )
        def close(self):
            pass

    with patch("app.downloader.ytdlp.yt_dlp.YoutubeDL", FakeYDL):
        from app.downloader.ytdlp import YtdlpDownloadError, download_audio
        try:
            download_audio("vid123", tmp_path, "mp3", ffmpeg_path="/fake/ffmpeg")
            assert False, "expected YtdlpDownloadError"
        except YtdlpDownloadError as exc:
            assert "Requested format is not available" in str(exc)
    assert attempts == [1]


def test_other_errors_with_cookies_do_not_trigger_the_cookie_less_retry(tmp_path, monkeypatch):
    """The fallback is scoped to the format-unavailable failure only — a
    genuinely unavailable video must not burn a second network attempt."""
    import yt_dlp
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    cookie_file = youtube_cookies_path()
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    cookie_file.write_text("# Netscape HTTP Cookie File\n")

    attempts = []

    class FakeYDL:
        def __init__(self, options):
            self.options = options
        def download(self, urls):
            attempts.append(1)
            raise yt_dlp.utils.DownloadError("ERROR: [youtube] vid123: Video unavailable")
        def close(self):
            pass

    with patch("app.downloader.ytdlp.yt_dlp.YoutubeDL", FakeYDL):
        from app.downloader.ytdlp import YtdlpDownloadError, download_audio
        try:
            download_audio("vid123", tmp_path, "mp3", ffmpeg_path="/fake/ffmpeg")
            assert False, "expected YtdlpDownloadError"
        except YtdlpDownloadError as exc:
            assert "Video unavailable" in str(exc)
    assert attempts == [1]


def test_real_download_failure_still_raises_even_if_close_also_fails(tmp_path, monkeypatch):
    """A genuine download failure must still surface — close()-time cleanup
    failures are only swallowed when the download itself succeeded."""
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "empty-config"))
    import yt_dlp

    class FakeYDL:
        def __init__(self, options):
            pass
        def download(self, urls):
            raise yt_dlp.utils.DownloadError("no formats found")
        def close(self):
            raise PermissionError(13, "Permission denied", "irrelevant")

    with patch("app.downloader.ytdlp.yt_dlp.YoutubeDL", FakeYDL):
        from app.downloader.ytdlp import YtdlpDownloadError, download_audio
        try:
            download_audio("vid123", tmp_path, "mp3", ffmpeg_path="/fake/ffmpeg")
            assert False, "expected YtdlpDownloadError"
        except YtdlpDownloadError as exc:
            assert "no formats found" in str(exc)
