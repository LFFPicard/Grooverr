"""
QueueItem persistence operations: enqueue, claim, complete, retry, cancel,
and startup recovery. All methods are synchronous and fast (local SQLite in
WAL mode); workers call them directly from the event loop, which also makes
job claiming race-free — claims never yield mid-transaction.
"""
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from app.db import engine
from app.models import (
    Album,
    Artist,
    JobStatus,
    JobType,
    QueueItem,
    Track,
    TrackStatus,
)
from app.queue.hub import hub

# Resolve jobs outrank downloads so metadata keeps flowing while the
# download slots are busy (lower number = higher priority).
PRIORITY_RESOLVE = 50
PRIORITY_DOWNLOAD = 100

PLACEHOLDER_ALBUM_TITLE = "Unknown Album"


def _job_event(job: QueueItem, track_title: Optional[str] = None) -> dict:
    return {
        "job": {
            "id": job.id,
            "track_id": job.track_id,
            "job_type": job.job_type.value if job.job_type else None,
            "status": job.status.value if job.status else None,
            "progress_percent": job.progress_percent,
            "error_message": job.error_message,
            "track_title": track_title,
        }
    }


class QueueService:
    """Stateless facade over the QueueItem table + the wake event."""

    def __init__(self):
        import asyncio
        self.wake = asyncio.Event()

    # ── Enqueue ───────────────────────────────────────────────────────────

    def add_track_request(
        self,
        title: str,
        artist: Optional[str] = None,
        album: Optional[str] = None,
        quality_kbps: Optional[int] = None,
        output_format: Optional[str] = None,
    ) -> tuple[str, str]:
        """Section 7.1 step 5 for a free-text add: create placeholder
        Artist/Album/Track rows (patched with canonical data once resolution
        runs) and enqueue a metadata_resolve job. Returns (track_id, job_id)."""
        with Session(engine) as session:
            artist_row = None
            if artist:
                artist_row = session.exec(
                    select(Artist).where(Artist.name == artist)
                ).first()
            if artist_row is None:
                artist_row = Artist(name=artist or "Unknown Artist")
                session.add(artist_row)
                session.flush()

            album_title = album or PLACEHOLDER_ALBUM_TITLE
            album_row = session.exec(
                select(Album).where(
                    Album.artist_id == artist_row.id, Album.title == album_title
                )
            ).first()
            if album_row is None:
                album_row = Album(artist_id=artist_row.id, title=album_title)
                session.add(album_row)
                session.flush()

            track = Track(album_id=album_row.id, title=title, status=TrackStatus.queued)
            session.add(track)
            session.flush()

            job = QueueItem(
                track_id=track.id,
                job_type=JobType.metadata_resolve,
                priority=PRIORITY_RESOLVE,
                requested_quality=str(quality_kbps) if quality_kbps else None,
                requested_format=output_format,
            )
            session.add(job)
            session.commit()
            track_id, job_id = track.id, job.id
            hub.publish("queue_update", _job_event(job, track_title=title))

        self.wake.set()
        return track_id, job_id

    def enqueue_resolve(
        self,
        track_id: str,
        quality: Optional[str] = None,
        output_format: Optional[str] = None,
    ) -> str:
        """Metadata-resolve job for an existing track row."""
        with Session(engine) as session:
            job = QueueItem(
                track_id=track_id,
                job_type=JobType.metadata_resolve,
                priority=PRIORITY_RESOLVE,
                requested_quality=quality,
                requested_format=output_format,
            )
            session.add(job)
            session.commit()
            track = session.get(Track, track_id)
            hub.publish("queue_update", _job_event(job, track.title if track else None))
            job_id = job.id
        self.wake.set()
        return job_id

    def enqueue_download(
        self,
        track_id: str,
        quality: Optional[str] = None,
        output_format: Optional[str] = None,
        session: Optional[Session] = None,
    ) -> str:
        def _create(s: Session) -> str:
            # Idempotent per track: a resolve job crash-recovered after it
            # already enqueued the download must not duplicate the work.
            existing = s.exec(
                select(QueueItem).where(
                    QueueItem.track_id == track_id,
                    QueueItem.job_type == JobType.download,
                    QueueItem.status.in_((JobStatus.queued, JobStatus.active)),  # type: ignore[attr-defined]
                )
            ).first()
            if existing is not None:
                return existing.id
            job = QueueItem(
                track_id=track_id,
                job_type=JobType.download,
                priority=PRIORITY_DOWNLOAD,
                requested_quality=quality,
                requested_format=output_format,
            )
            s.add(job)
            s.commit()
            track = s.get(Track, track_id)
            hub.publish("queue_update", _job_event(job, track.title if track else None))
            return job.id

        if session is not None:
            job_id = _create(session)
        else:
            with Session(engine) as s:
                job_id = _create(s)
        self.wake.set()
        return job_id

    # ── Worker-side lifecycle ─────────────────────────────────────────────

    def claim_next(self) -> Optional[QueueItem]:
        """Claim the highest-priority queued job (priority, then age).
        Safe without row locking: callers run on one event loop and this
        method never awaits."""
        with Session(engine) as session:
            job = session.exec(
                select(QueueItem)
                .where(QueueItem.status == JobStatus.queued)
                .order_by(QueueItem.priority, QueueItem.created_at)
                .limit(1)
            ).first()
            if job is None:
                return None
            job.status = JobStatus.active
            job.started_at = datetime.utcnow()
            session.add(job)
            session.commit()
            session.refresh(job)
            hub.publish("queue_update", _job_event(job, self._track_title(session, job)))
            return job

    def update_progress(self, job_id: str, percent: int) -> None:
        """Persist progress (Section 9.3: state written on every meaningful
        update). Thread-safe — called from yt-dlp's hook thread."""
        with Session(engine) as session:
            job = session.get(QueueItem, job_id)
            if job is None or job.status != JobStatus.active:
                return
            if percent <= (job.progress_percent or 0):
                return
            job.progress_percent = percent
            session.add(job)
            session.commit()
            hub.publish_threadsafe(
                "queue_update", _job_event(job, self._track_title(session, job))
            )

    def finish(self, job_id: str, error: Optional[str] = None) -> None:
        with Session(engine) as session:
            job = session.get(QueueItem, job_id)
            if job is None:
                return
            job.status = JobStatus.error if error else JobStatus.done
            job.error_message = error
            job.finished_at = datetime.utcnow()
            if not error:
                job.progress_percent = 100
            session.add(job)
            session.commit()
            hub.publish("queue_update", _job_event(job, self._track_title(session, job)))

    def release_to_queue(self, job_id: str) -> None:
        """Put a claimed job back (graceful shutdown mid-processing)."""
        with Session(engine) as session:
            job = session.get(QueueItem, job_id)
            if job is not None and job.status == JobStatus.active:
                job.status = JobStatus.queued
                job.started_at = None
                job.progress_percent = 0
                session.add(job)
                session.commit()

    # ── User actions ──────────────────────────────────────────────────────

    def retry(self, job_id: str) -> bool:
        """Reset an errored job to queued (Section 7.3 step 7: errors stay
        visible and retryable)."""
        with Session(engine) as session:
            job = session.get(QueueItem, job_id)
            if job is None or job.status != JobStatus.error:
                return False
            job.status = JobStatus.queued
            job.error_message = None
            job.progress_percent = 0
            job.started_at = None
            job.finished_at = None
            session.add(job)
            if job.track_id:
                track = session.get(Track, job.track_id)
                if track is not None and track.status == TrackStatus.error:
                    track.status = TrackStatus.queued
                    track.error_message = None
                    session.add(track)
            session.commit()
            hub.publish("queue_update", _job_event(job, self._track_title(session, job)))
        self.wake.set()
        return True

    def cancel(self, job_id: str) -> bool:
        """Remove a queued job. Active jobs can't be cancelled mid-flight in
        Batch 4 (revisited with the full queue UI) — returns False so the
        API can say so explicitly."""
        with Session(engine) as session:
            job = session.get(QueueItem, job_id)
            if job is None or job.status != JobStatus.queued:
                return False
            if job.track_id:
                track = session.get(Track, job.track_id)
                if track is not None and track.status == TrackStatus.queued:
                    track.status = TrackStatus.missing
                    session.add(track)
            session.delete(job)
            session.commit()
            hub.publish("queue_update", {"job": {"id": job_id, "status": "cancelled"}})
        return True

    # ── Startup recovery (Section 7.5) ────────────────────────────────────

    def recover_stuck_jobs(self) -> int:
        """Jobs left 'active' by an unclean shutdown go back to 'queued'."""
        with Session(engine) as session:
            stuck = session.exec(
                select(QueueItem).where(QueueItem.status == JobStatus.active)
            ).all()
            for job in stuck:
                job.status = JobStatus.queued
                job.started_at = None
                job.progress_percent = 0
                session.add(job)
            # Tracks stuck mid-download go back to queued as well.
            downloading = session.exec(
                select(Track).where(Track.status == TrackStatus.downloading)
            ).all()
            for track in downloading:
                track.status = TrackStatus.queued
                session.add(track)
            session.commit()
            if stuck:
                self.wake.set()
            return len(stuck)

    @staticmethod
    def _track_title(session: Session, job: QueueItem) -> Optional[str]:
        if not job.track_id:
            return None
        track = session.get(Track, job.track_id)
        return track.title if track else None
