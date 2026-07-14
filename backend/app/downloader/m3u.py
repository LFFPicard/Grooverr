"""
M3U8 playlist manifest generation (Section 6.1, decision resolved
2026-07-14): playlists never duplicate audio. Every member track is
downloaded once to its normal Section 6 path; the manifest is just a text
file of absolute paths into that existing structure.

The manifest is regenerated in full (never incrementally patched) whenever
a member track's download completes, so it fills in automatically as the
playlist's tracks finish downloading.

regenerate_playlist_m3u lives here rather than in app.api.playlists
deliberately: this module has no dependency on app.runtime/app.queue, so
both app.queue.pipeline and the API routes can import it without risking
the circular import that results from going through app.api.playlists
(which pulls in app.runtime -> app.queue's package __init__ -> pipeline).
"""
from datetime import datetime
from pathlib import Path
from typing import NamedTuple, Optional

from sqlmodel import Session, select

from app.downloader.paths import sanitize_component
from app.models import Album, Artist, Playlist, PlaylistTrack, Track, TrackStatus
from app.settings_store import music_root

PLAYLISTS_SUBDIR = "Playlists"


class M3UEntry(NamedTuple):
    file_path: str
    duration_seconds: Optional[int]
    artist_name: Optional[str]
    title: str


def resolve_m3u_path(
    playlist_id: str,
    playlist_name: str,
    existing_m3u_path: Optional[str],
    music_root: str,
    taken_paths: set[str],
) -> Path:
    """The manifest path is assigned once and reused for every future
    regeneration — a playlist's file doesn't move just because it's
    rewritten again. A name collision with a *different* playlist's
    already-assigned path gets a short id suffix to disambiguate."""
    if existing_m3u_path:
        return Path(existing_m3u_path)
    directory = Path(music_root) / PLAYLISTS_SUBDIR
    base_name = sanitize_component(playlist_name or "Untitled Playlist")
    candidate = directory / f"{base_name}.m3u8"
    # Path equality (not raw string comparison) so callers' path strings
    # compare correctly regardless of separator style.
    taken = {Path(p) for p in taken_paths}
    if candidate in taken:
        candidate = directory / f"{base_name} ({playlist_id[:8]}).m3u8"
    return candidate


def write_m3u(path: Path, entries: list[M3UEntry]) -> None:
    """Full rewrite. Only downloaded tracks are ever passed in by the
    caller — the file simply grows as more tracks complete."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["#EXTM3U"]
    for entry in entries:
        duration = entry.duration_seconds if entry.duration_seconds is not None else -1
        label = f"{entry.artist_name} - {entry.title}" if entry.artist_name else entry.title
        lines.append(f"#EXTINF:{duration},{label}")
        lines.append(entry.file_path)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def regenerate_playlist_m3u(session: Session, playlist: Playlist) -> None:
    """Full rewrite of the playlist's .m3u8 manifest — called on playlist
    creation and whenever a member track's download completes. Commits
    the session (updates Playlist.m3u_path/m3u_generated_at) as its own
    unit of work."""
    rows = session.exec(
        select(PlaylistTrack, Track, Album, Artist)
        .join(Track, Track.id == PlaylistTrack.track_id)  # type: ignore[arg-type]
        .outerjoin(Album, Album.id == Track.album_id)  # type: ignore[arg-type]
        .outerjoin(Artist, Artist.id == Album.artist_id)  # type: ignore[arg-type]
        .where(PlaylistTrack.playlist_id == playlist.id)
        .order_by(PlaylistTrack.position)
    ).all()
    entries = [
        M3UEntry(
            file_path=track.file_path,
            duration_seconds=track.duration_seconds,
            artist_name=artist.name if artist else None,
            title=track.title,
        )
        for _pt, track, _album, artist in rows
        if track.status == TrackStatus.downloaded and track.file_path
    ]

    # session.exec() on a single-column select returns bare scalars, not
    # Row tuples — no [0] indexing (that would slice into the string).
    taken = set(
        session.exec(
            select(Playlist.m3u_path).where(
                Playlist.m3u_path.is_not(None), Playlist.id != playlist.id  # type: ignore[union-attr]
            )
        )
    )
    path = resolve_m3u_path(playlist.id, playlist.name, playlist.m3u_path, music_root(), taken)
    write_m3u(path, entries)

    playlist.m3u_path = str(path)
    playlist.m3u_generated_at = datetime.utcnow()
    session.add(playlist)
    session.commit()
