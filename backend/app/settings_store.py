"""
Typed access to the Settings key/value table (values stored as JSON).

Defaults live here so every consumer sees the same fallback. The music
root comes from the MUSIC_DIR environment variable (a Docker volume, like
CONFIG_DIR), not from Settings.
"""
import json
import os
from typing import Any

from sqlmodel import Session

from app.db import engine
from app.models import Settings

DEFAULTS: dict[str, Any] = {
    "download_concurrency": 3,               # Section 9.3 default
    "default_quality_ceiling": None,         # kbps; None = best available
    "default_output_format": "mp3",
    "output_path_template": None,            # None = Section 6 default template
    "musicbrainz_user_agent": None,          # None = built-in Grooverr UA
    "duration_tolerance_seconds": 5,
}


def music_root() -> str:
    return os.environ.get("MUSIC_DIR", "/music")


def get_setting(key: str, session: Session | None = None) -> Any:
    def _read(s: Session) -> Any:
        row = s.get(Settings, key)
        if row is None:
            return DEFAULTS.get(key)
        try:
            return json.loads(row.value)
        except (ValueError, TypeError):
            return DEFAULTS.get(key)

    if session is not None:
        return _read(session)
    with Session(engine) as s:
        return _read(s)


def set_setting(key: str, value: Any, session: Session | None = None) -> None:
    def _write(s: Session) -> None:
        row = s.get(Settings, key)
        encoded = json.dumps(value)
        if row is None:
            s.add(Settings(key=key, value=encoded))
        else:
            row.value = encoded
            s.add(row)
        s.commit()

    if session is not None:
        _write(session)
    else:
        with Session(engine) as s:
            _write(s)
