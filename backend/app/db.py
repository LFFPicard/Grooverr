"""
Database engine setup.

WAL mode is mandatory (Section 9.1 of grooverr.md) — it allows the library UI
to keep reading smoothly while background workers write queue/download progress
concurrently. Do not remove the WAL pragma.
"""
import os
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import event
from sqlalchemy.engine import Engine

DATA_DIR = os.environ.get("CONFIG_DIR", "/config")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "grooverr.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """Applied to every new connection — WAL mode + NORMAL sync per Section 9.1."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.close()


def _ensure_column(connection, table: str, column: str, ddl: str) -> None:
    """Minimal additive migration: create_all() doesn't ALTER existing
    tables, so columns added after a DB was first created are backfilled
    here. Additive-only by design — anything more needs a real migration."""
    existing = {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")}
    if column not in existing:
        connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db():
    """Create all tables. Called once on startup."""
    from app import models  # noqa: F401 — import registers tables with SQLModel.metadata
    SQLModel.metadata.create_all(engine)
    with engine.begin() as connection:
        _ensure_column(connection, "album", "genre", "genre VARCHAR")
        _ensure_column(connection, "queueitem", "requested_format", "requested_format VARCHAR")
        _ensure_column(connection, "track", "has_artwork", "has_artwork BOOLEAN")
        _ensure_column(connection, "track", "youtube_video_id", "youtube_video_id VARCHAR")


def get_session():
    with Session(engine) as session:
        yield session
