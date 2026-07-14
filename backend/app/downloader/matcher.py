"""
Audio source matching (Section 7.3 steps 2-3).

Given a resolved track, find the best-matching audio on YouTube Music by
title + artist + duration. Duration matching within a few seconds is the
primary anti-mismatch signal; a candidate whose length is off by more than
the tolerance is rejected outright. If no YT Music song qualifies, fall
back to a plain YouTube video search with the same matching logic.

A pre-existing youtube_video_id (from a search result or playlist import)
is never trusted blindly — Section 7.3 (decision resolved 2026-07-13):
its actual duration is fetched and cross-checked with the same tolerance
as a fresh search match before it's used. A mismatch or failed lookup
falls through to a fresh title+artist+duration search rather than
downloading a possibly-wrong video.
"""
import logging
from typing import Optional

from pydantic import BaseModel

from app.resolver.schemas import ResolvedTrack
from app.resolver.ytmusic import YouTubeMusicClient

logger = logging.getLogger("grooverr.downloader.matcher")

DEFAULT_DURATION_TOLERANCE_SECONDS = 5


class AudioMatch(BaseModel):
    video_id: str
    title: str
    artist_name: Optional[str] = None
    duration_seconds: Optional[int] = None
    audio_source: str                        # "youtube-music" | "youtube"
    url: str


def _match_url(video_id: str, audio_source: str) -> str:
    host = "music.youtube.com" if audio_source == "youtube-music" else "www.youtube.com"
    return f"https://{host}/watch?v={video_id}"


def _best_candidate(
    candidates: list[ResolvedTrack],
    target_duration: Optional[int],
    tolerance: int,
) -> Optional[ResolvedTrack]:
    """First candidate within duration tolerance (results are already in
    YT Music relevance order). With no target duration to check against,
    the top result is trusted."""
    for candidate in candidates:
        if not candidate.youtube_video_id:
            continue
        if target_duration is None or candidate.duration_seconds is None:
            return candidate
        if abs(candidate.duration_seconds - target_duration) <= tolerance:
            return candidate
    return None


def _verify_existing_video_id(
    yt: YouTubeMusicClient,
    track: ResolvedTrack,
    tolerance_seconds: int,
) -> Optional[AudioMatch]:
    """Mandatory cross-check for a pre-existing video id (Section 7.3):
    fetch the candidate's actual duration and run it through the exact
    same tolerance check as a fresh search hit. Returns None — never
    raises — on mismatch or a failed/empty lookup, so the caller falls
    through to a real search instead of trusting an unverified id."""
    try:
        candidate = yt.get_track(track.youtube_video_id)
    except Exception:
        logger.exception("Duration cross-check lookup failed for video id %s", track.youtube_video_id)
        candidate = None
    verified = _best_candidate([candidate] if candidate else [], track.duration_seconds, tolerance_seconds)
    if verified is None:
        return None
    video_id = verified.youtube_video_id or track.youtube_video_id
    return AudioMatch(
        video_id=video_id,
        title=verified.title or track.title,
        artist_name=verified.artist_name or track.artist_name,
        duration_seconds=verified.duration_seconds,
        audio_source="youtube-music",
        url=_match_url(video_id, "youtube-music"),
    )


def find_audio_source(
    yt: YouTubeMusicClient,
    track: ResolvedTrack,
    tolerance_seconds: int = DEFAULT_DURATION_TOLERANCE_SECONDS,
) -> Optional[AudioMatch]:
    """Blocking (ytmusicapi is sync) — callers on the event loop should wrap
    in asyncio.to_thread."""
    if track.youtube_video_id:
        verified = _verify_existing_video_id(yt, track, tolerance_seconds)
        if verified is not None:
            return verified
        logger.info(
            "Pre-existing video id %s failed the duration cross-check for %r — falling back to search",
            track.youtube_video_id, track.title,
        )

    query = " ".join(part for part in (track.title, track.artist_name) if part)
    for search, source in ((yt.search_songs, "youtube-music"), (yt.search_videos, "youtube")):
        candidates = search(query, 10)
        best = _best_candidate(candidates, track.duration_seconds, tolerance_seconds)
        if best and best.youtube_video_id:
            return AudioMatch(
                video_id=best.youtube_video_id,
                title=best.title,
                artist_name=best.artist_name,
                duration_seconds=best.duration_seconds,
                audio_source=source,
                url=_match_url(best.youtube_video_id, source),
            )
    return None
