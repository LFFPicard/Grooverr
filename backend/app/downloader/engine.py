"""
Download engine — orchestrates the Section 7.3 pipeline for one track:

  match audio source → yt-dlp download + ffmpeg convert → embed tags +
  cover art → move to the Section 6 path under the music root.

Failures raise DownloadFailure with a specific, user-facing message (the
queue worker in Batch 4 stores it on Track.error_message — Section 7.3
step 7 forbids silent drops). Non-fatal problems (cover art unavailable)
are returned as warnings instead of failing the download.
"""
import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Optional

import httpx
from pydantic import BaseModel

from app.downloader.matcher import AudioMatch, find_audio_source
from app.downloader.paths import DEFAULT_PATH_TEMPLATE, render_track_path
from app.downloader.tagger import embed_tags
from app.downloader.ytdlp import YtdlpDownloadError, download_audio, resolve_ffmpeg_path
from app.resolver.schemas import ResolvedTrack
from app.resolver.ytmusic import YouTubeMusicClient

logger = logging.getLogger("grooverr.downloader")


class DownloadFailure(Exception):
    """User-facing failure; str(exc) is specific enough to show in the UI."""


class DownloadResult(BaseModel):
    file_path: str
    file_format: str
    bitrate_kbps: Optional[int] = None
    audio_source: str                      # "youtube-music" | "youtube"
    audio_source_url: str
    # The video id actually used — may differ from a stale pre-existing id
    # the caller passed in, if the Section 7.3 duration cross-check
    # rejected it and fell through to a fresh search match.
    video_id: str
    cover_embedded: bool
    warnings: list[str] = []


def _read_bitrate_kbps(path: Path) -> Optional[int]:
    try:
        import mutagen
        audio = mutagen.File(path)
        bitrate = getattr(getattr(audio, "info", None), "bitrate", None)
        if isinstance(bitrate, (int, float)) and bitrate > 0:
            return round(bitrate / 1000)
    except Exception:
        logger.exception("Could not read bitrate from %s", path)
    return None


class DownloadEngine:
    def __init__(
        self,
        music_root: str,
        ytmusic: Optional[YouTubeMusicClient] = None,
        path_template: str = DEFAULT_PATH_TEMPLATE,
        ffmpeg_path: Optional[str] = None,
        duration_tolerance_seconds: int = 5,
    ):
        self.music_root = music_root
        self.yt = ytmusic or YouTubeMusicClient()
        self.path_template = path_template
        self.ffmpeg_path = ffmpeg_path or resolve_ffmpeg_path()
        self.duration_tolerance_seconds = duration_tolerance_seconds

    async def _fetch_cover(self, track: ResolvedTrack, warnings: list[str]) -> Optional[bytes]:
        """Cover art is mandatory per Section 6, but an unavailable image is
        downgraded to a warning rather than failing the whole download.
        Tries the resolved URL, then the Cover Art Archive original-size
        fallback when the sized thumbnail 404s."""
        urls = []
        if track.cover_art_url:
            urls.append(track.cover_art_url)
            if "coverartarchive.org" in track.cover_art_url and "/front-" in track.cover_art_url:
                urls.append(track.cover_art_url.rsplit("/front-", 1)[0] + "/front")
        if not urls:
            warnings.append("No cover art URL in resolved metadata — file has no embedded art")
            return None
        async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
            for url in urls:
                try:
                    response = await client.get(url)
                    if response.status_code == 200 and response.content:
                        return response.content
                except httpx.HTTPError:
                    continue
        warnings.append(f"Cover art could not be fetched ({urls[0]}) — file has no embedded art")
        return None

    async def download_track(
        self,
        track: ResolvedTrack,
        output_format: str = "mp3",
        quality_kbps: Optional[int] = None,
        album_artist: Optional[str] = None,
        multi_disc: Optional[bool] = None,
        match: Optional[AudioMatch] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
        path_template: Optional[str] = None,
        duration_tolerance_seconds: Optional[int] = None,
    ) -> DownloadResult:
        """Download, tag and place one track. `multi_disc` drives the
        Section 6 disc-prefix rule; when the caller doesn't know the album's
        disc count it defaults to True only if the track sits on disc 2+.

        `path_template` / `duration_tolerance_seconds` are per-call
        overrides so the queue pipeline can apply the current Settings
        values on every job (like quality/format) rather than freezing the
        constructor values in at startup — the Batch 8 user-agent lesson."""
        warnings: list[str] = []
        tolerance = (
            duration_tolerance_seconds
            if duration_tolerance_seconds is not None
            else self.duration_tolerance_seconds
        )

        if match is None:
            match = await asyncio.to_thread(
                find_audio_source, self.yt, track, tolerance
            )
        if match is None:
            raise DownloadFailure(
                f"No YouTube Music or YouTube match found for "
                f"“{track.title}” ({track.artist_name or 'unknown artist'})"
            )

        if multi_disc is None:
            multi_disc = bool(track.disc_number and track.disc_number > 1)

        album_artist = album_artist or track.album_artist or track.artist_name
        final_path = render_track_path(
            music_root=self.music_root,
            title=track.title,
            album_artist=album_artist or "Unknown Artist",
            album=track.album_title or "Unknown Album",
            ext=output_format,
            track_number=track.track_number,
            disc_number=track.disc_number,
            release_year=track.release_year,
            multi_disc=multi_disc,
            template=path_template or self.path_template,
        )

        cover = await self._fetch_cover(track, warnings)

        with tempfile.TemporaryDirectory(prefix="grooverr-dl-") as tmp:
            try:
                downloaded = await asyncio.to_thread(
                    download_audio,
                    match.video_id,
                    Path(tmp),
                    output_format,
                    quality_kbps,
                    self.ffmpeg_path,
                    progress_callback,
                )
            except YtdlpDownloadError as exc:
                raise DownloadFailure(str(exc)) from exc

            try:
                await asyncio.to_thread(
                    embed_tags, downloaded, output_format, track, album_artist, cover
                )
            except Exception as exc:
                raise DownloadFailure(
                    f"Tagging failed for “{track.title}”: {exc}"
                ) from exc

            bitrate = _read_bitrate_kbps(downloaded)

            try:
                final_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(downloaded), str(final_path))
            except OSError as exc:
                raise DownloadFailure(
                    f"Could not place file at {final_path}: {exc}"
                ) from exc

        return DownloadResult(
            file_path=str(final_path),
            file_format=output_format,
            bitrate_kbps=bitrate,
            audio_source=match.audio_source,
            audio_source_url=match.url,
            video_id=match.video_id,
            cover_embedded=cover is not None,
            warnings=warnings,
        )
