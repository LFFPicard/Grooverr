"""
Settings CRUD. GET returns the effective settings (stored values merged
over defaults); PUT accepts a partial update and validates every key —
unknown keys and invalid values are rejected with specific messages.

Also (Batch 8): YouTube cookie file upload/status/removal, and an output
path template live-preview endpoint.
"""
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.downloader.paths import DEFAULT_PATH_TEMPLATE, render_track_path, sanitize_component
from app.downloader.ytdlp import SUPPORTED_FORMATS, YOUTUBE_COOKIES_FILENAME, youtube_cookies_path
from app.settings_store import DEFAULTS, get_setting, set_setting
from app import runtime

router = APIRouter(prefix="/api/settings", tags=["settings"])
MAX_COOKIE_FILE_BYTES = 1_000_000  # a real cookies.txt export is a few KB


def _validate_int_range(name: str, low: int, high: int, nullable: bool = False):
    def check(value: Any) -> Any:
        if value is None and nullable:
            return None
        if not isinstance(value, int) or isinstance(value, bool) or not (low <= value <= high):
            raise HTTPException(422, f"{name} must be an integer between {low} and {high}")
        return value
    return check


def _validate_format(value: Any) -> Any:
    if value not in SUPPORTED_FORMATS:
        raise HTTPException(
            422, f"default_output_format must be one of: {', '.join(SUPPORTED_FORMATS)}"
        )
    return value


def _validate_template(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(422, "output_path_template must be a non-empty string or null")
    try:
        render_track_path(
            music_root="/music", title="Title", album_artist="Artist", album="Album",
            ext="mp3", track_number=1, disc_number=1, release_year=2000,
            multi_disc=True, template=value,
        )
    except ValueError as exc:
        raise HTTPException(422, f"output_path_template is invalid: {exc}")
    return value


def _validate_optional_str(name: str):
    def check(value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(422, f"{name} must be a non-empty string or null")
        return value.strip()
    return check


def _validate_playlist_folder(value: Any) -> Any:
    """A relative path under MusicRoot (Section 6.1) — never absolute,
    never escaping MusicRoot via '..', and every segment must already be
    filesystem-safe (same rule as track/album names)."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(422, "playlist_output_folder must be a non-empty string or null")
    normalized = value.strip().replace("\\", "/").strip("/")
    segments = [s for s in normalized.split("/") if s != ""]
    if not segments or any(seg in (".", "..") for seg in normalized.split("/")):
        raise HTTPException(
            422, "playlist_output_folder must be a relative path with no '..' segments"
        )
    sanitized = [sanitize_component(seg) for seg in segments]
    if sanitized != segments:
        raise HTTPException(
            422,
            "playlist_output_folder contains characters that aren't safe in a folder name "
            f"(try: {'/'.join(sanitized)})",
        )
    return "/".join(segments)


_VALIDATORS = {
    "download_concurrency": _validate_int_range("download_concurrency", 1, 10),
    "default_quality_ceiling": _validate_int_range("default_quality_ceiling", 32, 320, nullable=True),
    "default_output_format": _validate_format,
    "output_path_template": _validate_template,
    "musicbrainz_user_agent": _validate_optional_str("musicbrainz_user_agent"),
    "duration_tolerance_seconds": _validate_int_range("duration_tolerance_seconds", 1, 60),
    "playlist_output_folder": _validate_playlist_folder,
}


class SettingsOut(BaseModel):
    download_concurrency: int
    default_quality_ceiling: Optional[int] = None
    default_output_format: str
    output_path_template: Optional[str] = None
    musicbrainz_user_agent: Optional[str] = None
    duration_tolerance_seconds: int
    playlist_output_folder: Optional[str] = None


class SettingsUpdate(BaseModel):
    download_concurrency: Optional[int] = None
    default_quality_ceiling: Optional[int] = None
    default_output_format: Optional[str] = None
    output_path_template: Optional[str] = None
    musicbrainz_user_agent: Optional[str] = None
    duration_tolerance_seconds: Optional[int] = None
    playlist_output_folder: Optional[str] = None


def _effective() -> dict:
    return {key: get_setting(key) for key in DEFAULTS}


@router.get("", response_model=SettingsOut)
def read_settings():
    return SettingsOut(**_effective())


@router.put("", response_model=SettingsOut)
def update_settings(body: SettingsUpdate):
    """Partial update — only keys present in the request body change.
    Explicit nulls reset nullable settings to their default."""
    provided = body.model_dump(exclude_unset=True)
    if not provided:
        raise HTTPException(422, "No settings provided")
    for key, value in provided.items():
        validated = _VALIDATORS[key](value)
        set_setting(key, validated)
        if key == "musicbrainz_user_agent":
            # MusicBrainz rate-limits by user-agent — must apply to the
            # live client immediately, not just on next restart.
            from app.resolver.musicbrainz import DEFAULT_USER_AGENT
            runtime.resolver.mb.set_user_agent(validated or DEFAULT_USER_AGENT)
    return SettingsOut(**_effective())


# ── YouTube cookie file (Section: "Credentials stored in /config volume,
# never in the music output volume") ────────────────────────────────────

class CookieStatus(BaseModel):
    configured: bool
    uploaded_at: Optional[str] = None


def _cookie_status() -> CookieStatus:
    path = youtube_cookies_path()
    return CookieStatus(
        configured=path.is_file(),
        uploaded_at=get_setting("youtube_cookies_uploaded_at") if path.is_file() else None,
    )


@router.get("/youtube-cookies", response_model=CookieStatus)
def youtube_cookies_status():
    return _cookie_status()


@router.post("/youtube-cookies", response_model=CookieStatus, status_code=201)
async def upload_youtube_cookies(file: UploadFile = File(...)):
    content = await file.read()
    if not content:
        raise HTTPException(422, "Uploaded file is empty")
    if len(content) > MAX_COOKIE_FILE_BYTES:
        raise HTTPException(
            422, f"File is too large to be a {YOUTUBE_COOKIES_FILENAME} export (max 1 MB)"
        )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            422, "File is not valid text — expected a Netscape-format cookies.txt export"
        )
    has_cookie_line = any(
        line.strip() and not line.startswith("#") and line.count("\t") >= 5
        for line in text.splitlines()
    )
    if not has_cookie_line:
        raise HTTPException(
            422,
            "This doesn't look like a Netscape-format cookies.txt file — export one with "
            "a 'Get cookies.txt' browser extension while logged into YouTube",
        )

    path = youtube_cookies_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    uploaded_at = datetime.utcnow().isoformat()
    set_setting("youtube_cookies_uploaded_at", uploaded_at)
    return CookieStatus(configured=True, uploaded_at=uploaded_at)


@router.delete("/youtube-cookies", response_model=CookieStatus)
def delete_youtube_cookies():
    path = youtube_cookies_path()
    if path.is_file():
        path.unlink()
    set_setting("youtube_cookies_uploaded_at", None)
    return CookieStatus(configured=False, uploaded_at=None)


# ── Output path template live preview ────────────────────────────────────

class PathPreview(BaseModel):
    template: str
    single_disc_example: str
    multi_disc_example: str


@router.get("/preview-path", response_model=PathPreview)
def preview_path_template(template: Optional[str] = None):
    """Renders the Section 6 examples (a single-disc and a multi-disc
    album) through the real render_track_path — so the preview can never
    drift from actual download-time behavior."""
    active_template = template if template is not None else (
        get_setting("output_path_template") or DEFAULT_PATH_TEMPLATE
    )
    try:
        single = render_track_path(
            music_root="/music", title="Give Life Back to Music", album_artist="Daft Punk",
            album="Random Access Memories", ext="flac", track_number=1, disc_number=1,
            release_year=2013, multi_disc=False, template=active_template,
        )
        multi = render_track_path(
            music_root="/music", title="Supersymmetry", album_artist="Arcade Fire",
            album="Reflektor", ext="mp3", track_number=3, disc_number=2,
            release_year=2013, multi_disc=True, template=active_template,
        )
    except ValueError as exc:
        raise HTTPException(422, f"Template is invalid: {exc}")
    return PathPreview(
        template=active_template,
        # .as_posix() (not str()) so this preview matches what the actual
        # Docker/Linux deployment produces, regardless of what OS Grooverr
        # is being developed/previewed on.
        single_disc_example=single.as_posix(),
        multi_disc_example=multi.as_posix(),
    )
