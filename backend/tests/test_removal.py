"""
Section 7.6 tests: queue bulk clear ("Clear failed"/"Clear completed") and
library deletion (track/album/artist/playlist, each with a delete_files
choice). Covers the FK-constrained cascade (QueueItem/PlaylistTrack rows
must be removed before their Track — Section 9.1 enforces real FK
constraints) and the delete_files disk-cleanup path (file removal + now-
empty folder cleanup), not just the DB-row bookkeeping.
"""
import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import engine
from app.main import app
from app.models import Album, Artist, JobStatus, Playlist, PlaylistTrack, QueueItem, Track, TrackStatus
from app.resolver.schemas import MetadataSource, ResolvedAlbum, ResolvedPlaylist, ResolvedTrack
from app.settings_store import music_root

client = TestClient(app)


def _write_music_file(relative: str) -> str:
    path = Path(music_root()) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake-audio")
    return str(path)


def _resolved_album(track_count=2, mbid="rel-1", title="Album"):
    return ResolvedAlbum(
        title=title, artist_name="Artist", album_type="album", release_year=2013,
        total_tracks=track_count, musicbrainz_id=mbid, musicbrainz_artist_id="art-1",
        tracks=[
            ResolvedTrack(
                title=f"T{n}", artist_name="Artist", album_artist="Artist",
                album_title=title, track_number=n, disc_number=1, duration_seconds=200,
                musicbrainz_id=f"rec-{mbid}-{n}", musicbrainz_release_id=mbid,
                source=MetadataSource.musicbrainz,
            )
            for n in range(1, track_count + 1)
        ],
        source=MetadataSource.musicbrainz,
    )


def _add_album(track_count=2, mbid="rel-1", title="Album"):
    response = client.post(
        "/api/library/add",
        json={"type": "album", "album": _resolved_album(track_count, mbid, title).model_dump(mode="json")},
    )
    assert response.status_code == 202, response.text
    return response.json()


def _add_empty_playlist(title="Playlist"):
    playlist = ResolvedPlaylist(title=title, source=MetadataSource.youtube_music, tracks=[])
    response = client.post(
        "/api/library/add", json={"type": "playlist", "playlist": playlist.model_dump(mode="json")}
    )
    assert response.status_code == 202, response.text
    return response.json()["added_playlist_id"]


# ── Queue bulk clear ────────────────────────────────────────────────────────

def test_clear_failed_removes_only_error_jobs(clean_db):
    _add_album(track_count=3)
    with Session(engine) as session:
        jobs = session.exec(select(QueueItem)).all()
        jobs[0].status = JobStatus.error
        jobs[0].error_message = "boom"
        jobs[1].status = JobStatus.done
        session.add(jobs[0])
        session.add(jobs[1])
        session.commit()

    response = client.post("/api/queue/clear", params={"status": "error"})
    assert response.status_code == 200
    assert response.json() == {"cleared": 1, "status": "error"}

    with Session(engine) as session:
        remaining = session.exec(select(QueueItem)).all()
        assert len(remaining) == 2
        assert all(j.status != JobStatus.error for j in remaining)
        # Metadata-only: Track rows are never touched by a queue clear.
        assert len(session.exec(select(Track)).all()) == 3


def test_clear_done_removes_only_done_jobs(clean_db):
    _add_album(track_count=3)
    with Session(engine) as session:
        jobs = session.exec(select(QueueItem)).all()
        jobs[0].status = JobStatus.done
        jobs[1].status = JobStatus.error
        jobs[1].error_message = "boom"
        session.add(jobs[0])
        session.add(jobs[1])
        session.commit()

    response = client.post("/api/queue/clear", params={"status": "done"})
    assert response.status_code == 200
    assert response.json() == {"cleared": 1, "status": "done"}

    with Session(engine) as session:
        remaining = session.exec(select(QueueItem)).all()
        assert len(remaining) == 2
        assert all(j.status != JobStatus.done for j in remaining)


def test_clear_rejects_non_terminal_statuses(clean_db):
    assert client.post("/api/queue/clear", params={"status": "queued"}).status_code == 422
    assert client.post("/api/queue/clear", params={"status": "active"}).status_code == 422


# ── Track deletion ──────────────────────────────────────────────────────────

def test_delete_track_default_leaves_file_on_disk(clean_db):
    body = _add_album(track_count=1, mbid="rel-t1", title="Keep File Album")
    track_id = body["added_track_ids"][0]
    file_path = _write_music_file("KeepFileArtist/Keep File Album (2013)/01 - T1.mp3")
    with Session(engine) as session:
        track = session.get(Track, track_id)
        track.file_path = file_path
        track.status = TrackStatus.downloaded
        session.add(track)
        session.commit()

    response = client.delete(f"/api/library/tracks/{track_id}")
    assert response.status_code == 200
    assert response.json()["files_deleted"] is False

    assert os.path.exists(file_path)
    with Session(engine) as session:
        assert session.get(Track, track_id) is None


def test_delete_track_with_delete_files_removes_file_and_empty_dirs(clean_db):
    body = _add_album(track_count=1, mbid="rel-t2", title="Remove File Album")
    track_id = body["added_track_ids"][0]
    file_path = _write_music_file("RemoveFileArtist/Remove File Album (2013)/01 - T1.mp3")
    album_dir = Path(file_path).parent
    artist_dir = album_dir.parent
    with Session(engine) as session:
        track = session.get(Track, track_id)
        track.file_path = file_path
        track.status = TrackStatus.downloaded
        session.add(track)
        session.commit()

    response = client.delete(f"/api/library/tracks/{track_id}", params={"delete_files": "true"})
    assert response.status_code == 200
    assert response.json()["files_deleted"] is True

    assert not os.path.exists(file_path)
    assert not album_dir.exists()   # emptied by the only track's removal
    assert not artist_dir.exists()  # emptied in turn — no other album left


def test_delete_track_removes_associated_queue_items(clean_db):
    body = _add_album(track_count=1, mbid="rel-t3", title="Queue History Album")
    track_id = body["added_track_ids"][0]
    with Session(engine) as session:
        jobs = session.exec(select(QueueItem).where(QueueItem.track_id == track_id)).all()
        assert len(jobs) == 1  # the auto-enqueued download job

    response = client.delete(f"/api/library/tracks/{track_id}")
    assert response.status_code == 200

    with Session(engine) as session:
        assert session.exec(select(QueueItem).where(QueueItem.track_id == track_id)).all() == []


def test_delete_track_cascades_playlist_membership_and_regenerates_m3u(clean_db):
    body1 = _add_album(track_count=1, mbid="rel-p1", title="P Album 1")
    body2 = _add_album(track_count=1, mbid="rel-p2", title="P Album 2")
    track1_id = body1["added_track_ids"][0]
    track2_id = body2["added_track_ids"][0]

    file1 = _write_music_file("PArtist/P Album 1 (2013)/01 - t1.mp3")
    file2 = _write_music_file("PArtist/P Album 2 (2013)/01 - t2.mp3")
    with Session(engine) as session:
        for tid, fp in ((track1_id, file1), (track2_id, file2)):
            track = session.get(Track, tid)
            track.file_path = fp
            track.status = TrackStatus.downloaded
            session.add(track)
        session.commit()

    playlist_id = _add_empty_playlist("Del Test Playlist")
    with Session(engine) as session:
        session.add(PlaylistTrack(playlist_id=playlist_id, track_id=track1_id, position=1))
        session.add(PlaylistTrack(playlist_id=playlist_id, track_id=track2_id, position=2))
        session.commit()
        playlist = session.get(Playlist, playlist_id)
        from app.downloader.m3u import regenerate_playlist_m3u
        regenerate_playlist_m3u(session, playlist)
        m3u_path = playlist.m3u_path

    content_before = Path(m3u_path).read_text()
    assert Path(file1).name in content_before
    assert Path(file2).name in content_before

    response = client.delete(f"/api/library/tracks/{track1_id}")
    assert response.status_code == 200
    assert response.json()["affected_playlists"] == 1

    with Session(engine) as session:
        links = session.exec(
            select(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id)
        ).all()
        assert [link.track_id for link in links] == [track2_id]
        playlist = session.get(Playlist, playlist_id)
        content_after = Path(playlist.m3u_path).read_text()
    assert Path(file1).name not in content_after
    assert Path(file2).name in content_after


def test_delete_nonexistent_track_404s(clean_db):
    assert client.delete("/api/library/tracks/does-not-exist").status_code == 404


# ── Album deletion ───────────────────────────────────────────────────────────

def test_delete_album_default_leaves_files(clean_db):
    body = _add_album(track_count=1, mbid="rel-album-keep", title="Keep Album")
    album_id = body["added_album_id"]
    with Session(engine) as session:
        track = session.exec(select(Track).where(Track.album_id == album_id)).one()
        file_path = _write_music_file("KeepArtist/Keep Album (2013)/01 - keep.mp3")
        track.file_path = file_path
        track.status = TrackStatus.downloaded
        session.add(track)
        session.commit()

    response = client.delete(f"/api/library/albums/{album_id}")
    assert response.status_code == 200
    assert response.json()["files_deleted"] is False
    assert os.path.exists(file_path)
    with Session(engine) as session:
        assert session.get(Album, album_id) is None


def test_delete_album_cascades_tracks_and_cleans_empty_folder(clean_db):
    body = _add_album(track_count=2, mbid="rel-album-del", title="Deletable Album")
    album_id = body["added_album_id"]
    files = []
    with Session(engine) as session:
        tracks = session.exec(select(Track).where(Track.album_id == album_id)).all()
        for i, track in enumerate(tracks):
            file_path = _write_music_file(
                f"DelArtist/Deletable Album (2013)/0{i + 1} - {track.title}.mp3"
            )
            track.file_path = file_path
            track.status = TrackStatus.downloaded
            session.add(track)
            files.append(file_path)
        session.commit()
    album_dir = Path(files[0]).parent
    artist_dir = album_dir.parent

    response = client.delete(f"/api/library/albums/{album_id}", params={"delete_files": "true"})
    assert response.status_code == 200
    body = response.json()
    assert body["cascaded_tracks"] == 2
    assert body["files_deleted"] is True

    with Session(engine) as session:
        assert session.get(Album, album_id) is None
        assert session.exec(select(Track).where(Track.album_id == album_id)).all() == []
    for file_path in files:
        assert not os.path.exists(file_path)
    assert not album_dir.exists()
    assert not artist_dir.exists()


def test_delete_nonexistent_album_404s(clean_db):
    assert client.delete("/api/library/albums/does-not-exist").status_code == 404


# ── Artist deletion ──────────────────────────────────────────────────────────

def test_delete_artist_cascades_albums_and_tracks(clean_db):
    album1 = client.post(
        "/api/library/add",
        json={"type": "album", "album": _resolved_album(1, "rel-art-1", "Artist Album 1").model_dump(mode="json")},
    ).json()
    client.post(
        "/api/library/add",
        json={"type": "album", "album": _resolved_album(1, "rel-art-2", "Artist Album 2").model_dump(mode="json")},
    )
    with Session(engine) as session:
        artist_id = session.get(Album, album1["added_album_id"]).artist_id

    response = client.delete(f"/api/library/artists/{artist_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["cascaded_albums"] == 2
    assert body["cascaded_tracks"] == 2

    with Session(engine) as session:
        assert session.get(Artist, artist_id) is None
        assert session.exec(select(Album).where(Album.artist_id == artist_id)).all() == []


def test_delete_artist_with_delete_files_removes_all_files_and_empty_dirs(clean_db):
    album1 = client.post(
        "/api/library/add",
        json={"type": "album", "album": _resolved_album(1, "rel-artdel-1", "AD Album 1").model_dump(mode="json")},
    ).json()
    album2 = client.post(
        "/api/library/add",
        json={"type": "album", "album": _resolved_album(1, "rel-artdel-2", "AD Album 2").model_dump(mode="json")},
    ).json()
    with Session(engine) as session:
        artist_id = session.get(Album, album1["added_album_id"]).artist_id
        track1 = session.exec(select(Track).where(Track.album_id == album1["added_album_id"])).one()
        track2 = session.exec(select(Track).where(Track.album_id == album2["added_album_id"])).one()
        file1 = _write_music_file("ADArtist/AD Album 1 (2013)/01 - t1.mp3")
        file2 = _write_music_file("ADArtist/AD Album 2 (2013)/01 - t2.mp3")
        track1.file_path = file1
        track1.status = TrackStatus.downloaded
        track2.file_path = file2
        track2.status = TrackStatus.downloaded
        session.add(track1)
        session.add(track2)
        session.commit()
    artist_dir = Path(file1).parent.parent

    response = client.delete(f"/api/library/artists/{artist_id}", params={"delete_files": "true"})
    assert response.status_code == 200
    assert not os.path.exists(file1)
    assert not os.path.exists(file2)
    assert not artist_dir.exists()  # both albums gone → artist folder emptied too


def test_delete_nonexistent_artist_404s(clean_db):
    assert client.delete("/api/library/artists/does-not-exist").status_code == 404


# ── Playlist deletion ────────────────────────────────────────────────────────

def test_delete_playlist_does_not_touch_tracks(clean_db):
    body = _add_album(track_count=1, mbid="rel-plkeep", title="PL Keep Album")
    track_id = body["added_track_ids"][0]
    playlist_id = _add_empty_playlist("Solo Playlist")
    with Session(engine) as session:
        session.add(PlaylistTrack(playlist_id=playlist_id, track_id=track_id, position=1))
        session.commit()

    response = client.delete(f"/api/library/playlists/{playlist_id}")
    assert response.status_code == 200
    assert response.json()["cascaded_tracks"] == 1

    with Session(engine) as session:
        assert session.get(Playlist, playlist_id) is None
        assert session.get(Track, track_id) is not None  # untouched
        assert session.exec(
            select(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id)
        ).all() == []


def test_delete_playlist_default_leaves_manifest_file(clean_db):
    playlist_id = _add_empty_playlist("Manifest Keep Playlist")
    with Session(engine) as session:
        m3u_path = session.get(Playlist, playlist_id).m3u_path
    assert m3u_path and os.path.exists(m3u_path)

    response = client.delete(f"/api/library/playlists/{playlist_id}")
    assert response.status_code == 200
    assert response.json()["files_deleted"] is False
    assert os.path.exists(m3u_path)


def test_delete_playlist_with_delete_files_removes_manifest(clean_db):
    playlist_id = _add_empty_playlist("Manifest Delete Playlist")
    with Session(engine) as session:
        m3u_path = session.get(Playlist, playlist_id).m3u_path
    assert m3u_path and os.path.exists(m3u_path)

    response = client.delete(f"/api/library/playlists/{playlist_id}", params={"delete_files": "true"})
    assert response.status_code == 200
    assert response.json()["files_deleted"] is True
    assert not os.path.exists(m3u_path)


def test_delete_nonexistent_playlist_404s(clean_db):
    assert client.delete("/api/library/playlists/does-not-exist").status_code == 404
