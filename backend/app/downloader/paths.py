"""
File naming & folder convention (grooverr.md Section 6).

Default template (MusicBrainz Picard-compatible, ships out of the box):

    {MusicRoot}/{AlbumArtist}/{Album} ({ReleaseYear})/{DiscNumber-}{TrackNumber} - {Title}.{ext}

Rules implemented here:
- `{DiscNumber-}` renders as "2-" only when the album has more than one disc,
  else as nothing.
- Track number always zero-padded to 2 digits.
- Illegal filesystem characters (/ \\ : * ? " < > |) replaced with "-" in
  every rendered component (never in the template's own separators).
- The template is user-configurable via Settings; unknown tokens raise so a
  bad template fails loudly at preview/save time instead of scattering
  files.

Note: the spec calls for a "Jinja-style" template string. What's implemented
is simple {Token} substitution covering the default template's tokens —
logged in the Section 11 assumptions log.
"""
import re
from pathlib import Path
from typing import Optional

DEFAULT_PATH_TEMPLATE = (
    "{MusicRoot}/{AlbumArtist}/{Album} ({ReleaseYear})/"
    "{DiscNumber-}{TrackNumber} - {Title}.{ext}"
)

_ILLEGAL_CHARS = re.compile(r'[/\\:*?"<>|]')
_CONTROL_CHARS = re.compile(r"[\x00-\x1f]")
_TOKEN = re.compile(r"\{([A-Za-z]+-?)\}")


def sanitize_component(value: str) -> str:
    """Make a single path component (folder or file name) filesystem-safe."""
    value = _ILLEGAL_CHARS.sub("-", value)
    value = _CONTROL_CHARS.sub(" ", value)
    value = " ".join(value.split())          # collapse runs of whitespace
    value = value.strip(". ")                # Windows: no trailing dots/spaces
    return value or "_"


def render_track_path(
    music_root: str,
    title: str,
    album_artist: str,
    album: str,
    ext: str,
    track_number: Optional[int] = None,
    disc_number: Optional[int] = None,
    release_year: Optional[int] = None,
    multi_disc: bool = False,
    template: str = DEFAULT_PATH_TEMPLATE,
) -> Path:
    """Render the output path for a track. Every metadata value is sanitized
    individually so e.g. an artist named "AC/DC" cannot create extra folders."""
    if release_year is None:
        # No year → drop the " (YYYY)" decoration rather than render "(None)".
        template = re.sub(r"\s*\(\{ReleaseYear\}\)", "", template)

    values = {
        "MusicRoot": music_root.rstrip("/\\"),
        "AlbumArtist": sanitize_component(album_artist or "Unknown Artist"),
        "Artist": sanitize_component(album_artist or "Unknown Artist"),
        "Album": sanitize_component(album or "Unknown Album"),
        "ReleaseYear": str(release_year) if release_year is not None else "",
        "DiscNumber-": f"{disc_number}-" if (multi_disc and disc_number) else "",
        "DiscNumber": str(disc_number) if disc_number else "",
        "TrackNumber": f"{track_number:02d}" if track_number else "00",
        "Title": sanitize_component(title or "Unknown Title"),
        "ext": ext.lstrip(".").lower(),
    }

    unknown = [t for t in _TOKEN.findall(template) if t not in values]
    if unknown:
        raise ValueError(f"Unknown template token(s): {', '.join(sorted(set(unknown)))}")

    rendered = _TOKEN.sub(lambda m: values.get(m.group(1), ""), template)
    return Path(rendered)
