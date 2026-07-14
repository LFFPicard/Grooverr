"""
Integration tests for Section 6.1's manifest regeneration: the
orchestration function that queries the DB and writes the file, and the
pipeline hook that fires it when a member track's download completes.
"""
import os
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session

from app.db import engine
from app.downloader.m3u import regenerate_playlist_m3u
from app.models import Album, Artist, Playlist, PlaylistTrack, Track, TrackStatus
from app.settings_store import set_setting


def make_track(session, title, status=TrackStatus.missing, file_path=None, position=1):
    artist = Artist(name=f"Artist for {title}")
    session.add(artist)
    session.flush()
    album = Album(artist_id=artist.id, title=f"Album for {title}")
    session.add(album)
    session.flush()
    track = Track(album_id=album.id, title=title, status=status, file_path=file_path,
                  duration_seconds=200)
    session.add(track)
    session.flush()
    return track


def test_regenerate_only_includes_downloaded_tracks_with_a_path(clean_db):
    with Session(engine) as session:
        playlist = Playlist(name="Mixed Completeness")
        session.add(playlist)
        session.flush()

        downloaded = make_track(session, "Done", status=TrackStatus.downloaded,
                                file_path="/music/A/Album for Done/Done.mp3")
        missing = make_track(session, "Missing", status=TrackStatus.missing)
        session.add(PlaylistTrack(playlist_id=playlist.id, track_id=downloaded.id, position=1))
        session.add(PlaylistTrack(playlist_id=playlist.id, track_id=missing.id, position=2))
        session.commit()

        regenerate_playlist_m3u(session, playlist)

        assert playlist.m3u_path is not None
        assert playlist.m3u_generated_at is not None
        content = open(playlist.m3u_path, encoding="utf-8").read()
        assert "Done.mp3" in content
        assert "Missing" not in content   # not downloaded — excluded


def test_regenerate_is_idempotent_on_path_across_calls(clean_db):
    with Session(engine) as session:
        playlist = Playlist(name="Stable Path Test")
        session.add(playlist)
        session.flush()
        session.commit()

        regenerate_playlist_m3u(session, playlist)
        first_path = playlist.m3u_path
        first_generated_at = playlist.m3u_generated_at

        regenerate_playlist_m3u(session, playlist)
        assert playlist.m3u_path == first_path              # same file, not renamed
        assert playlist.m3u_generated_at >= first_generated_at


def test_regenerate_disambiguates_same_named_playlists(clean_db):
    with Session(engine) as session:
        p1 = Playlist(name="Favorites")
        p2 = Playlist(name="Favorites")
        session.add(p1)
        session.add(p2)
        session.commit()

        regenerate_playlist_m3u(session, p1)
        regenerate_playlist_m3u(session, p2)
        assert p1.m3u_path != p2.m3u_path
        assert os.path.basename(p1.m3u_path) == "Favorites.m3u8"
        assert p2.m3u_path.endswith(".m3u8")
        assert p2.id[:8] in p2.m3u_path


def test_regenerate_reflects_growing_completeness(clean_db):
    with Session(engine) as session:
        playlist = Playlist(name="Growing Mix")
        session.add(playlist)
        session.flush()
        track = make_track(session, "Not Yet")
        session.add(PlaylistTrack(playlist_id=playlist.id, track_id=track.id, position=1))
        session.commit()

        regenerate_playlist_m3u(session, playlist)
        assert open(playlist.m3u_path, encoding="utf-8").read() == "#EXTM3U\n"

        track.status = TrackStatus.downloaded
        track.file_path = "/music/X/Album for Not Yet/Not Yet.mp3"
        session.add(track)
        session.commit()
        regenerate_playlist_m3u(session, playlist)
        content = open(playlist.m3u_path, encoding="utf-8").read()
        assert "Not Yet.mp3" in content


def test_regenerate_uses_relative_paths(clean_db, tmp_path):
    with Session(engine) as session:
        playlist = Playlist(name="Relative Path Mix")
        session.add(playlist)
        session.flush()
        track_dir = tmp_path / "Real Artist" / "Real Album (2013)"
        track_dir.mkdir(parents=True)
        track_file = track_dir / "01 - Real Track.mp3"
        track_file.write_bytes(b"fake")
        track = make_track(session, "Real Track", status=TrackStatus.downloaded,
                           file_path=str(track_file))
        session.add(PlaylistTrack(playlist_id=playlist.id, track_id=track.id, position=1))
        session.commit()

        import app.downloader.m3u as m3u_module
        with patch.object(m3u_module, "music_root", return_value=str(tmp_path)):
            regenerate_playlist_m3u(session, playlist)

        lines = open(playlist.m3u_path, encoding="utf-8").read().splitlines()
        path_line = lines[2]
        assert not os.path.isabs(path_line)
        resolved = (Path(playlist.m3u_path).parent / path_line).resolve()
        assert resolved == track_file.resolve()


def test_regenerate_relocates_on_folder_setting_change(clean_db, tmp_path):
    """Batch 8 DoD: changing playlist_output_folder and regenerating an
    existing playlist writes to the new location, not the old default,
    and cleans up the stale file."""
    import app.downloader.m3u as m3u_module

    with Session(engine) as session, patch.object(
        m3u_module, "music_root", return_value=str(tmp_path)
    ):
        playlist = Playlist(name="Relocating Mix")
        session.add(playlist)
        session.flush()
        session.commit()

        regenerate_playlist_m3u(session, playlist)
        old_path = Path(playlist.m3u_path)
        assert old_path.parent.name == "Playlists"          # default
        assert old_path.is_file()

        set_setting("playlist_output_folder", "My Custom Mixes")
        regenerate_playlist_m3u(session, playlist)
        new_path = Path(playlist.m3u_path)

        assert new_path.parent.name == "My Custom Mixes"
        assert new_path.name == old_path.name                # filename unchanged
        assert new_path.is_file()
        assert not old_path.exists()                          # stale file cleaned up
