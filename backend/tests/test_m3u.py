"""
M3U8 manifest generation tests (Section 6.1). Playlists never duplicate
audio — only a manifest referencing existing Artist/Album paths (via
relative links, so {MusicRoot} stays portable as a unit) is generated/
regenerated. The output folder is Settings-configurable.
"""
from pathlib import Path

from app.downloader.m3u import M3UEntry, resolve_m3u_path, write_m3u


def test_resolve_m3u_path_default_location():
    path = resolve_m3u_path("id-1", "Road Trip", None, "/music", "Playlists", taken_paths=set())
    assert path == Path("/music/Playlists/Road Trip.m3u8")


def test_resolve_m3u_path_honors_configured_folder():
    path = resolve_m3u_path("id-1", "Road Trip", None, "/music", "My Mixes", taken_paths=set())
    assert path == Path("/music/My Mixes/Road Trip.m3u8")


def test_resolve_m3u_path_keeps_filename_but_moves_to_new_folder():
    """Filename is sticky across regenerations (renames don't move the
    file); the directory always tracks the *current* configured folder,
    so a folder-setting change relocates existing playlists."""
    path = resolve_m3u_path(
        "id-1", "Renamed Later", "/music/Playlists/Original.m3u8", "/music", "New Folder", set()
    )
    assert path == Path("/music/New Folder/Original.m3u8")


def test_resolve_m3u_path_sanitizes_illegal_characters():
    path = resolve_m3u_path("id-1", "Rock / Metal: 90s?", None, "/music", "Playlists", set())
    assert path.name == "Rock - Metal- 90s-.m3u8"


def test_resolve_m3u_path_disambiguates_name_collision():
    taken = {"/music/Playlists/Road Trip.m3u8"}
    path = resolve_m3u_path("abcdef12-3456", "Road Trip", None, "/music", "Playlists", taken)
    assert path == Path("/music/Playlists/Road Trip (abcdef12).m3u8")


def test_write_m3u_format_uses_relative_paths(tmp_path):
    target = tmp_path / "Playlists" / "Mix.m3u8"
    entries = [
        M3UEntry(file_path=str(tmp_path / "Artist A" / "Album" / "01 - One.mp3"),
                duration_seconds=200, artist_name="Artist A", title="One"),
        M3UEntry(file_path=str(tmp_path / "Artist B" / "Album" / "02 - Two.mp3"),
                duration_seconds=None, artist_name=None, title="Two"),
    ]
    write_m3u(target, entries)
    assert target.is_file()
    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "#EXTM3U"
    assert lines[1] == "#EXTINF:200,Artist A - One"
    assert lines[2] == "../Artist A/Album/01 - One.mp3"       # relative, not absolute
    assert lines[3] == "#EXTINF:-1,Two"
    assert lines[4] == "../Artist B/Album/02 - Two.mp3"


def test_write_m3u_relative_path_is_actually_resolvable(tmp_path):
    """The whole point of relative paths: resolving them from the
    manifest's own folder must land on the real file."""
    track_dir = tmp_path / "Daft Punk" / "Random Access Memories (2013)"
    track_dir.mkdir(parents=True)
    track_file = track_dir / "01 - Give Life Back to Music.flac"
    track_file.write_bytes(b"fake audio")

    manifest = tmp_path / "Playlists" / "Mix.m3u8"
    write_m3u(manifest, [
        M3UEntry(file_path=str(track_file), duration_seconds=275, artist_name="Daft Punk",
                title="Give Life Back to Music"),
    ])
    relative_line = manifest.read_text(encoding="utf-8").splitlines()[2]
    resolved = (manifest.parent / relative_line).resolve()
    assert resolved == track_file.resolve()


def test_write_m3u_empty_entries_still_writes_header(tmp_path):
    target = tmp_path / "Playlists" / "Empty.m3u8"
    write_m3u(target, [])
    assert target.read_text(encoding="utf-8") == "#EXTM3U\n"


def test_write_m3u_creates_parent_directory(tmp_path):
    target = tmp_path / "nested" / "Playlists" / "Mix.m3u8"
    write_m3u(target, [])
    assert target.is_file()


def test_write_m3u_is_a_full_rewrite_not_incremental(tmp_path):
    target = tmp_path / "Playlists" / "Mix.m3u8"
    write_m3u(target, [M3UEntry(file_path=str(tmp_path / "a.mp3"), duration_seconds=100,
                                artist_name="A", title="T1")])
    first = target.read_text(encoding="utf-8")
    assert "a.mp3" in first

    write_m3u(target, [M3UEntry(file_path=str(tmp_path / "b.mp3"), duration_seconds=100,
                                artist_name="A", title="T2")])
    second = target.read_text(encoding="utf-8")
    assert "a.mp3" not in second
    assert "b.mp3" in second
