"""
Settings CRUD. GET returns the effective settings (stored values merged
over defaults); PUT accepts a partial update and validates every key —
unknown keys and invalid values are rejected with specific messages.
"""
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.downloader.paths import render_track_path
from app.downloader.ytdlp import SUPPORTED_FORMATS
from app.settings_store import DEFAULTS, get_setting, set_setting

router = APIRouter(prefix="/api/settings", tags=["settings"])


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


_VALIDATORS = {
    "download_concurrency": _validate_int_range("download_concurrency", 1, 10),
    "default_quality_ceiling": _validate_int_range("default_quality_ceiling", 32, 320, nullable=True),
    "default_output_format": _validate_format,
    "output_path_template": _validate_template,
    "musicbrainz_user_agent": _validate_optional_str("musicbrainz_user_agent"),
    "duration_tolerance_seconds": _validate_int_range("duration_tolerance_seconds", 1, 60),
}


class SettingsOut(BaseModel):
    download_concurrency: int
    default_quality_ceiling: Optional[int] = None
    default_output_format: str
    output_path_template: Optional[str] = None
    musicbrainz_user_agent: Optional[str] = None
    duration_tolerance_seconds: int


class SettingsUpdate(BaseModel):
    download_concurrency: Optional[int] = None
    default_quality_ceiling: Optional[int] = None
    default_output_format: Optional[str] = None
    output_path_template: Optional[str] = None
    musicbrainz_user_agent: Optional[str] = None
    duration_tolerance_seconds: Optional[int] = None


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
        set_setting(key, _VALIDATORS[key](value))
    return SettingsOut(**_effective())
