"""
M3U8 manifest generation tests (Section 6.1, decision resolved 2026-07-14).
Playlists never duplicate audio — only a manifest referencing existing
Artist/Album paths is generated/regenerated.
"""
from pathlib import Path

from app.downloader.m3u import M3UEntry, resolve_m3u_path, write_m3u


def test_resolve_m3u_path_default_location():
    path = resolve_m3u_path("id-1", "Road Trip", None, "/music", taken_paths=set())
    assert path == Path("/music/Playlists/Road Trip.m3u8")


def test_resolve_m3u_path_reuses_existing_assignment():
    path = resolve_m3u_path("id-1", "Renamed Later", "/music/Playlists/Original.m3u8", "/music", set())
    assert path == Path("/music/Playlists/Original.m3u8")   # unchanged despite name drift


def test_resolve_m3u_path_sanitizes_illegal_characters():
    path = resolve_m3u_path("id-1", "Rock / Metal: 90s?", None, "/music", set())
    assert path.name == "Rock - Metal- 90s-.m3u8"


def test_resolve_m3u_path_disambiguates_name_collision():
    taken = {"/music/Playlists/Road Trip.m3u8"}
    path = resolve_m3u_path("abcdef12-3456", "Road Trip", None, "/music", taken)
    assert path == Path("/music/Playlists/Road Trip (abcdef12).m3u8")


def test_write_m3u_format(tmp_path):
    target = tmp_path / "Playlists" / "Mix.m3u8"
    entries = [
        M3UEntry(file_path="/music/A/B/01 - One.mp3", duration_seconds=200,
                artist_name="Artist A", title="One"),
        M3UEntry(file_path="/music/C/D/02 - Two.mp3", duration_seconds=None,
                artist_name=None, title="Two"),
    ]
    write_m3u(target, entries)
    assert target.is_file()
    content = target.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert lines[0] == "#EXTM3U"
    assert lines[1] == "#EXTINF:200,Artist A - One"
    assert lines[2] == "/music/A/B/01 - One.mp3"
    assert lines[3] == "#EXTINF:-1,Two"              # no duration -> -1, no artist -> title only
    assert lines[4] == "/music/C/D/02 - Two.mp3"


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
    write_m3u(target, [M3UEntry(file_path="/a.mp3", duration_seconds=100, artist_name="A", title="T1")])
    first = target.read_text(encoding="utf-8")
    assert "/a.mp3" in first

    # Regeneration with a track no longer downloaded must not leave stale entries.
    write_m3u(target, [M3UEntry(file_path="/b.mp3", duration_seconds=100, artist_name="A", title="T2")])
    second = target.read_text(encoding="utf-8")
    assert "/a.mp3" not in second
    assert "/b.mp3" in second
