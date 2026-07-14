"""
Dev/test data seeding — bulk-inserts a large synthetic library so
pagination, filtering and index usage can be verified against realistic
row counts (Batch 5 DoD: 1,000+ albums, not a 5-row dev dataset).
"""
import random
import uuid
from datetime import datetime

from sqlalchemy import insert, select

from app.db import engine
from app.models import Album, Artist, Playlist, PlaylistTrack, Track

FIRST = ["Velvet", "Neon", "Crimson", "Silver", "Echo", "Lunar", "Golden", "Static",
         "Wild", "Broken", "Electric", "Paper", "Hollow", "Midnight", "Glass"]
SECOND = ["Foxes", "Harbor", "Monolith", "Cartographers", "Parade", "Reverie",
          "Machinery", "Gardens", "Antennae", "Pilots", "Choir", "Atlas"]
NOUNS = ["Dreams", "Wires", "Rivers", "Signals", "Shadows", "Postcards", "Engines",
         "Mirrors", "Satellites", "Currents", "Lanterns", "Horizons"]


def seed_library(album_count: int = 1200, tracks_per_album: int = 10,
                 seed: int = 42) -> dict:
    """Insert ~album_count/8 artists, album_count albums, and tracks with a
    mix of completeness states. Returns counts. Idempotent enough for dev
    use (fresh ids every run — run against a clean DB for exact counts)."""
    rng = random.Random(seed)
    now = datetime.utcnow()

    artists = [
        {"id": str(uuid.uuid4()), "name": f"{rng.choice(FIRST)} {rng.choice(SECOND)} {i}",
         "sort_name": None, "musicbrainz_id": None, "spotify_id": None, "created_at": now}
        for i in range(max(1, album_count // 8))
    ]
    albums, tracks = [], []
    for i in range(album_count):
        artist = rng.choice(artists)
        total = tracks_per_album
        album_id = str(uuid.uuid4())
        # Mix of completeness: ~40% complete, ~40% partial, ~20% empty.
        roll = rng.random()
        downloaded = total if roll < 0.4 else (rng.randint(1, total - 1) if roll < 0.8 else 0)
        albums.append({
            "id": album_id, "artist_id": artist["id"],
            "title": f"{rng.choice(FIRST)} {rng.choice(NOUNS)} Vol. {i}",
            "musicbrainz_id": None, "spotify_id": None,
            "release_year": rng.randint(1965, 2026), "album_type": "album",
            "total_tracks": total, "cover_art_url": None, "genre": None,
            "created_at": now,
        })
        for n in range(1, total + 1):
            is_downloaded = n <= downloaded
            tracks.append({
                "id": str(uuid.uuid4()), "album_id": album_id,
                "title": f"Track {n}", "track_number": n, "disc_number": 1,
                "duration_seconds": rng.randint(120, 420),
                "musicbrainz_id": None, "spotify_id": None,
                "file_path": f"/music/x/{album_id}/{n:02d}.mp3" if is_downloaded else None,
                "file_format": "mp3" if is_downloaded else None,
                "bitrate": "192" if is_downloaded else None,
                "status": "downloaded" if is_downloaded else "missing",
                "audio_source": "youtube-music" if is_downloaded else None,
                "audio_source_url": None, "error_message": None,
                "created_at": now, "downloaded_at": now if is_downloaded else None,
            })

    with engine.begin() as connection:
        connection.execute(insert(Artist), artists)
        connection.execute(insert(Album), albums)
        for start in range(0, len(tracks), 5000):
            connection.execute(insert(Track), tracks[start:start + 5000])
    return {"artists": len(artists), "albums": len(albums), "tracks": len(tracks)}


def seed_playlists(playlist_count: int = 40, tracks_per_playlist: int = 15,
                   seed: int = 43) -> dict:
    """Insert playlist_count Playlist rows, each linking (via PlaylistTrack)
    to a random sample of already-seeded tracks — run after seed_library so
    there's a track pool to draw from. Batch 7 DoD: 'a realistic set of
    seeded playlists' for the Library screen's Playlists tab."""
    rng = random.Random(seed)
    now = datetime.utcnow()

    with engine.begin() as connection:
        track_ids = [row[0] for row in connection.execute(select(Track.id))]
    if not track_ids:
        raise RuntimeError("seed_playlists requires tracks already in the DB — run seed_library first")

    playlists, playlist_tracks = [], []
    for i in range(playlist_count):
        playlist_id = str(uuid.uuid4())
        playlists.append({
            "id": playlist_id,
            "name": f"{rng.choice(FIRST)} {rng.choice(SECOND)} Mix {i}",
            "source": "youtube-music",
            "source_url": None,
            "source_playlist_id": f"PLseed{i}",
            "created_at": now,
        })
        sample = rng.sample(track_ids, k=min(tracks_per_playlist, len(track_ids)))
        for position, track_id in enumerate(sample, start=1):
            playlist_tracks.append({
                "id": str(uuid.uuid4()), "playlist_id": playlist_id,
                "track_id": track_id, "position": position,
            })

    with engine.begin() as connection:
        connection.execute(insert(Playlist), playlists)
        for start in range(0, len(playlist_tracks), 5000):
            connection.execute(insert(PlaylistTrack), playlist_tracks[start:start + 5000])
    return {"playlists": len(playlists), "playlist_tracks": len(playlist_tracks)}


if __name__ == "__main__":
    import sys
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 1200
    playlist_count = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    from app.db import init_db
    init_db()
    print(seed_library(count))
    print(seed_playlists(playlist_count))
