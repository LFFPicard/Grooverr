"""
yt-dlp wrapper — downloads audio for a video id at a quality ceiling and
converts to the target output format via ffmpeg.

Blocking (yt-dlp is sync); the engine wraps calls in asyncio.to_thread.
"""
import os
import shutil
from pathlib import Path
from typing import Callable, Optional

import yt_dlp

# Output format → yt-dlp FFmpegExtractAudio codec name.
_CODEC_BY_FORMAT = {
    "mp3": "mp3",
    "flac": "flac",
    "m4a": "m4a",
    "opus": "opus",
    "wav": "wav",
    "ogg": "vorbis",
}
SUPPORTED_FORMATS = tuple(_CODEC_BY_FORMAT)
LOSSY_FORMATS = ("mp3", "m4a", "opus", "ogg")


class YtdlpDownloadError(Exception):
    pass


def resolve_ffmpeg_path() -> Optional[str]:
    """ffmpeg binary: GROOVERR_FFMPEG env override > system PATH >
    imageio-ffmpeg's bundled static build (dev convenience — the Docker
    image installs a real ffmpeg)."""
    override = os.environ.get("GROOVERR_FFMPEG")
    if override:
        return override
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return None


def download_audio(
    video_id: str,
    dest_dir: Path,
    output_format: str = "mp3",
    quality_kbps: Optional[int] = None,
    ffmpeg_path: Optional[str] = None,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> Path:
    """Download + convert one video's audio. Returns the converted file path
    inside dest_dir. Raises YtdlpDownloadError on any failure."""
    if output_format not in _CODEC_BY_FORMAT:
        raise YtdlpDownloadError(
            f"Unsupported output format {output_format!r} (supported: {', '.join(SUPPORTED_FORMATS)})"
        )
    ffmpeg_path = ffmpeg_path or resolve_ffmpeg_path()
    if not ffmpeg_path:
        raise YtdlpDownloadError(
            "No ffmpeg binary found (set GROOVERR_FFMPEG or install ffmpeg)"
        )

    dest_dir.mkdir(parents=True, exist_ok=True)
    # Quality ceiling: prefer a source stream at/below the ceiling, fall back
    # to best available; the ceiling is also applied at the ffmpeg re-encode
    # for lossy targets.
    fmt = "bestaudio/best"
    if quality_kbps:
        fmt = f"bestaudio[abr<={quality_kbps}]/{fmt}"

    postprocessor = {
        "key": "FFmpegExtractAudio",
        "preferredcodec": _CODEC_BY_FORMAT[output_format],
    }
    if quality_kbps and output_format in LOSSY_FORMATS:
        postprocessor["preferredquality"] = str(quality_kbps)

    options = {
        "format": fmt,
        "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
        "postprocessors": [postprocessor],
        "ffmpeg_location": ffmpeg_path,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    if progress_callback is not None:
        # Transfer maps to 0-95%; the last 5% is the ffmpeg conversion.
        # Invoked on yt-dlp's worker thread — callbacks must be thread-safe.
        def hook(status: dict) -> None:
            if status.get("status") != "downloading":
                return
            total = status.get("total_bytes") or status.get("total_bytes_estimate")
            done = status.get("downloaded_bytes")
            if isinstance(total, (int, float)) and total > 0 and isinstance(done, (int, float)):
                try:
                    progress_callback(min(95, int(done / total * 95)))
                except Exception:
                    pass  # progress reporting must never kill the download

        options["progress_hooks"] = [hook]

    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as exc:
        raise YtdlpDownloadError(f"yt-dlp failed for {video_id}: {exc}") from exc

    result = dest_dir / f"{video_id}.{output_format}"
    if not result.is_file():
        raise YtdlpDownloadError(
            f"yt-dlp reported success but {result.name} was not produced"
        )
    return result
