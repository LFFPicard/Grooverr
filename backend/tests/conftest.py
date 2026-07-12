"""
Test bootstrap: point CONFIG_DIR/MUSIC_DIR at throwaway temp dirs BEFORE
any app module is imported (app.db binds the engine at import time).
"""
import os
import tempfile

os.environ["CONFIG_DIR"] = tempfile.mkdtemp(prefix="grooverr-test-config-")
os.environ["MUSIC_DIR"] = tempfile.mkdtemp(prefix="grooverr-test-music-")

import pytest  # noqa: E402


@pytest.fixture
def clean_db():
    """Initialised, empty database for queue/pipeline tests."""
    from sqlalchemy import delete
    from sqlmodel import Session

    from app import models
    from app.db import engine, init_db

    init_db()
    yield
    with Session(engine) as session:
        # Child tables (FK dependents) before their parents.
        for model in (models.PlaylistTrack, models.QueueItem, models.Track,
                      models.Playlist, models.Album, models.Artist, models.Settings):
            session.exec(delete(model))
        session.commit()
