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


def init_db():
    """Create all tables. Called once on startup."""
    from app import models  # noqa: F401 — import registers tables with SQLModel.metadata
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
