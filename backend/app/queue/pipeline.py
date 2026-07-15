"""
Job handlers — wire the Batch 2 resolver and Batch 3 download engine into
the queue (Sections 7.2 / 7.3).

metadata_resolve: resolve canonical metadata, patch the Artist/Album/Track
rows, then enqueue a download job for the track.

download: build resolved metadata from the DB rows, hand it to the download
engine, persist the outcome on the Track.

Every failure lands on Track.error_message + QueueItem.error_message with a
specific description — never silently dropped (Section 7.3 step 7).
"""
import logging
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from app.db import engine as db_engine
from app.downloader.engine import DownloadEngine, DownloadFailure
from app.downloader.m3u import regenerate_playlist_m3u
from app.models import Album, Artist, AudioSource, Playlist, PlaylistTrack, QueueItem, Track, TrackStatus
from app.queue.service import PLACEHOLDER_ALBUM_TITLE, QueueService
from app.resolver.engine import MetadataResolver
from app.resolver.schemas import MetadataSource, ResolvedTrack
from app.settings_store import get_setting, music_root

logger = logging.getLogger("grooverr.pipeline")


class Pipeline:
    def __init__(
        self,
        queue: QueueService,
        resolver: Optional[MetadataResolver] = None,
        downloader: Optional[DownloadEngine] = None,
    ):
        self.queue = queue
        self.resolver = resolver or MetadataResolver()
        self.downloader = downloader or DownloadEngine(
            music_root=music_root(), ytmusic=self.resolver.yt
        )

    async def process(self, job: QueueItem) -> None:
        """Run one claimed job to done/error state."""
        try:
            if job.job_type.value == "metadata_resolve":
                await self._resolve(job)
            elif job.job_type.value == "download":
                await self._download(job)
            elif job.job_type.value == "album_add":
                await self._album_add(job)
            else:
                raise RuntimeError(f"Unknown job type {job.job_type!r}")
        except Exception as exc:
            # Last-resort catch: anything a handler didn't turn into a clean
            # error state still must not vanish from the queue.
            logger.exception("Job %s failed", job.id)
            self._mark_track_error(job.track_id, str(exc))
            self.queue.finish(job.id, error=str(exc))

    # ── album_add (Section 11 item 15, post-audit) ─────────────────────────

    async def _album_add(self, job: QueueItem) -> None:
        """One release from a bulk 'Add entire discography' run — resolves
        + persists + enqueues downloads via the exact same _add_album() a
        manual single-album 'Add to library' click uses. Deferred import:
        app.api.library -> app.runtime -> app.queue (this package's own
        __init__, which imports workers -> pipeline) would be a circular
        import at module load time if this were a top-level import — the
        same trap Section 6.1 already documented once for playlists."""
        from app.api.library import _add_album
        from fastapi import HTTPException
        from app.resolver.schemas import ResolvedAlbum

        if not job.payload:
            self.queue.finish(job.id, error="album_add job has no payload")
            return
        try:
            resolved_album = ResolvedAlbum.model_validate_json(job.payload)
        except ValueError as exc:
            self.queue.finish(job.id, error=f"Malformed album_add payload: {exc}")
            return

        try:
            await _add_album(
                resolved_album,
                quality=job.requested_quality,
                output_format=job.requested_format,
            )
        except HTTPException as exc:
            message = f"Could not add “{resolved_album.title}”: {exc.detail}"
            self.queue.finish(job.id, error=message)
            return
        self.queue.finish(job.id)

    # ── metadata_resolve (Section 7.2) ────────────────────────────────────

    async def _resolve(self, job: QueueItem) -> None:
        with Session(db_engine) as session:
            track = session.get(Track, job.track_id) if job.track_id else None
            if track is None:
                self.queue.finish(job.id, error="Track row no longer exists")
                return
            album = session.get(Album, track.album_id)
            artist = session.get(Artist, album.artist_id) if album else None
            title = track.title
            artist_name = artist.name if artist and artist.name != "Unknown Artist" else None
            album_title = (
                album.title
                if album and album.title != PLACEHOLDER_ALBUM_TITLE
                else None
            )

        resolved = await self.resolver.resolve_track(
            title, artist=artist_name, album=album_title
        )
        if resolved is None:
            message = (
                f"No metadata match found for “{title}”"
                f"{f' by {artist_name}' if artist_name else ''} "
                "on MusicBrainz or YouTube Music"
            )
            self._mark_track_error(job.track_id, message)
            self.queue.finish(job.id, error=message)
            return

        self._apply_resolved(job.track_id, resolved)
        self.queue.finish(job.id)
        self.queue.enqueue_download(
            job.track_id,
            quality=job.requested_quality,
            output_format=job.requested_format,
        )

    def _apply_resolved(self, track_id: str, resolved: ResolvedTrack) -> None:
        """Section 7.2 step 4: populate/patch the rows with what was found."""
        with Session(db_engine) as session:
            track = session.get(Track, track_id)
            if track is None:
                return
            album = session.get(Album, track.album_id)
            artist = session.get(Artist, album.artist_id) if album else None

            track.title = resolved.title or track.title
            track.track_number = resolved.track_number
            track.disc_number = resolved.disc_number
            track.duration_seconds = resolved.duration_seconds
            track.musicbrainz_id = resolved.musicbrainz_id
            if resolved.youtube_video_id:
                track.youtube_video_id = resolved.youtube_video_id
                track.audio_source_url = (
                    f"https://music.youtube.com/watch?v={resolved.youtube_video_id}"
                )
            session.add(track)

            if artist is not None:
                name = resolved.album_artist or resolved.artist_name
                if name:
                    artist.name = name
                artist.musicbrainz_id = resolved.musicbrainz_artist_id or artist.musicbrainz_id
                session.add(artist)

            if album is not None:
                if resolved.album_title:
                    album.title = resolved.album_title
                album.release_year = resolved.release_year or album.release_year
                album.musicbrainz_id = resolved.musicbrainz_release_id or album.musicbrainz_id
                album.cover_art_url = resolved.cover_art_url or album.cover_art_url
                album.genre = resolved.genre or album.genre
                session.add(album)

            session.commit()

    # ── download (Section 7.3) ────────────────────────────────────────────

    async def _download(self, job: QueueItem) -> None:
        with Session(db_engine) as session:
            track = session.get(Track, job.track_id) if job.track_id else None
            if track is None:
                self.queue.finish(job.id, error="Track row no longer exists")
                return
            album = session.get(Album, track.album_id)
            artist = session.get(Artist, album.artist_id) if album else None

            resolved = ResolvedTrack(
                title=track.title,
                artist_name=artist.name if artist else None,
                album_artist=artist.name if artist else None,
                album_title=album.title if album else None,
                track_number=track.track_number,
                disc_number=track.disc_number,
                duration_seconds=track.duration_seconds,
                release_year=album.release_year if album else None,
                genre=album.genre if album else None,
                musicbrainz_id=track.musicbrainz_id,
                musicbrainz_release_id=album.musicbrainz_id if album else None,
                musicbrainz_artist_id=artist.musicbrainz_id if artist else None,
                cover_art_url=album.cover_art_url if album else None,
                # Fed to the matcher's mandatory duration cross-check
                # (Section 7.3) — never trusted blindly, just a candidate.
                youtube_video_id=track.youtube_video_id,
                source=MetadataSource.musicbrainz if track.musicbrainz_id
                else MetadataSource.youtube_music,
            )
            # Multi-disc rule: any track of this album on disc 2+ means the
            # album has more than one disc.
            multi_disc = False
            if album is not None:
                multi_disc = any(
                    (t.disc_number or 1) > 1
                    for t in session.exec(select(Track).where(Track.album_id == album.id))
                )

            track.status = TrackStatus.downloading
            track.error_message = None
            session.add(track)
            session.commit()

        quality = None
        if job.requested_quality and str(job.requested_quality).isdigit():
            quality = int(job.requested_quality)
        elif get_setting("default_quality_ceiling"):
            quality = int(get_setting("default_quality_ceiling"))
        output_format = job.requested_format or get_setting("default_output_format") or "mp3"
        # Read per job, like quality/format above — Settings changes must
        # apply to the next download, not freeze at engine construction
        # (full-audit finding 2026-07-15; same bug class as the Batch 8
        # user-agent fix).
        path_template = get_setting("output_path_template") or None
        tolerance = get_setting("duration_tolerance_seconds")

        job_id = job.id
        try:
            result = await self.downloader.download_track(
                resolved,
                output_format=output_format,
                quality_kbps=quality,
                multi_disc=multi_disc,
                progress_callback=lambda pct: self.queue.update_progress(job_id, pct),
                path_template=path_template,
                duration_tolerance_seconds=tolerance if isinstance(tolerance, int) else None,
            )
        except DownloadFailure as exc:
            self._mark_track_error(job.track_id, str(exc))
            self.queue.finish(job.id, error=str(exc))
            return

        with Session(db_engine) as session:
            track = session.get(Track, job.track_id)
            if track is not None:
                track.status = TrackStatus.downloaded
                track.file_path = result.file_path
                track.file_format = result.file_format
                track.bitrate = str(result.bitrate_kbps) if result.bitrate_kbps else None
                track.audio_source = AudioSource(result.audio_source)
                track.audio_source_url = result.audio_source_url
                # May differ from the pre-download value if the cross-check
                # rejected a stale id and fell through to a fresh match.
                track.youtube_video_id = result.video_id
                track.has_artwork = result.cover_embedded
                track.downloaded_at = datetime.utcnow()
                track.error_message = None
                session.add(track)
                session.commit()

                # Section 6.1: regenerate the manifest of any playlist this
                # track belongs to, now that it has a file_path.
                member_playlists = session.exec(
                    select(Playlist)
                    .join(PlaylistTrack, PlaylistTrack.playlist_id == Playlist.id)
                    .where(PlaylistTrack.track_id == track.id)
                ).all()
                for playlist in member_playlists:
                    regenerate_playlist_m3u(session, playlist)
        for warning in result.warnings:
            logger.warning("Download of %r: %s", resolved.title, warning)
        self.queue.finish(job.id)

    def _mark_track_error(self, track_id: Optional[str], message: str) -> None:
        if not track_id:
            return
        with Session(db_engine) as session:
            track = session.get(Track, track_id)
            if track is not None:
                track.status = TrackStatus.error
                track.error_message = message
                session.add(track)
                session.commit()
