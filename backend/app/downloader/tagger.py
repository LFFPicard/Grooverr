"""
Tag writing via mutagen (Section 6).

Tags written on every file: title, artist, album artist, album, track
number, disc number, year, genre (when available), and the MusicBrainz
track/release/artist IDs as custom tags using MusicBrainz Picard's own
mappings per container — this is what makes files Picard-compatible for
future re-tagging. Embedded cover art on every file.

Container mapping:
  mp3 / wav      → ID3v2 (WAV carries an ID3 chunk)
  flac           → Vorbis comments + FLAC picture block
  ogg / opus     → Vorbis comments + base64 METADATA_BLOCK_PICTURE
  m4a            → MP4 atoms + iTunes freeform MusicBrainz atoms
"""
import base64
from pathlib import Path
from typing import Optional

from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    ID3,
    APIC,
    TALB,
    TCON,
    TDRC,
    TIT2,
    TPE1,
    TPE2,
    TPOS,
    TRCK,
    TXXX,
    UFID,
)
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE

from app.resolver.schemas import ResolvedTrack


def _cover_mime(cover: bytes) -> str:
    if cover.startswith(b"\x89PNG"):
        return "image/png"
    return "image/jpeg"


def _write_id3(tags: ID3, track: ResolvedTrack, album_artist: str, cover: Optional[bytes]) -> None:
    tags.delall("APIC")
    tags.add(TIT2(encoding=3, text=track.title))
    if track.artist_name:
        tags.add(TPE1(encoding=3, text=track.artist_name))
    tags.add(TPE2(encoding=3, text=album_artist))
    if track.album_title:
        tags.add(TALB(encoding=3, text=track.album_title))
    if track.track_number:
        tags.add(TRCK(encoding=3, text=str(track.track_number)))
    if track.disc_number:
        tags.add(TPOS(encoding=3, text=str(track.disc_number)))
    if track.release_year:
        tags.add(TDRC(encoding=3, text=str(track.release_year)))
    if track.genre:
        tags.add(TCON(encoding=3, text=track.genre))
    # Picard's ID3 mapping: recording MBID lives in a UFID frame, the rest
    # in TXXX frames with these exact descriptions.
    if track.musicbrainz_id:
        tags.add(UFID(owner="http://musicbrainz.org", data=track.musicbrainz_id.encode()))
    if track.musicbrainz_release_id:
        tags.add(TXXX(encoding=3, desc="MusicBrainz Album Id", text=track.musicbrainz_release_id))
    if track.musicbrainz_artist_id:
        tags.add(TXXX(encoding=3, desc="MusicBrainz Artist Id", text=track.musicbrainz_artist_id))
    if cover:
        tags.add(APIC(encoding=3, mime=_cover_mime(cover), type=3, desc="Front cover", data=cover))


def _vorbis_comments(track: ResolvedTrack, album_artist: str) -> dict[str, str]:
    comments = {"TITLE": track.title, "ALBUMARTIST": album_artist}
    if track.artist_name:
        comments["ARTIST"] = track.artist_name
    if track.album_title:
        comments["ALBUM"] = track.album_title
    if track.track_number:
        comments["TRACKNUMBER"] = str(track.track_number)
    if track.disc_number:
        comments["DISCNUMBER"] = str(track.disc_number)
    if track.release_year:
        comments["DATE"] = str(track.release_year)
    if track.genre:
        comments["GENRE"] = track.genre
    if track.musicbrainz_id:
        comments["MUSICBRAINZ_TRACKID"] = track.musicbrainz_id
    if track.musicbrainz_release_id:
        comments["MUSICBRAINZ_ALBUMID"] = track.musicbrainz_release_id
    if track.musicbrainz_artist_id:
        comments["MUSICBRAINZ_ARTISTID"] = track.musicbrainz_artist_id
    return comments


def _flac_picture(cover: bytes) -> Picture:
    picture = Picture()
    picture.type = 3  # front cover
    picture.mime = _cover_mime(cover)
    picture.desc = "Front cover"
    picture.data = cover
    return picture


def embed_tags(
    path: Path,
    output_format: str,
    track: ResolvedTrack,
    album_artist: Optional[str] = None,
    cover: Optional[bytes] = None,
) -> None:
    """Write all Section 6 tags (+ cover art) to the file in place."""
    album_artist = album_artist or track.artist_name or "Unknown Artist"

    if output_format in ("mp3", "wav"):
        if output_format == "mp3":
            try:
                tags = ID3(path)
            except Exception:
                tags = ID3()
            _write_id3(tags, track, album_artist, cover)
            tags.save(path)
        else:
            audio = WAVE(path)
            if audio.tags is None:
                audio.add_tags()
            _write_id3(audio.tags, track, album_artist, cover)
            audio.save()
        return

    if output_format == "flac":
        audio = FLAC(path)
        for key, value in _vorbis_comments(track, album_artist).items():
            audio[key] = value
        audio.clear_pictures()
        if cover:
            audio.add_picture(_flac_picture(cover))
        audio.save()
        return

    if output_format in ("ogg", "opus"):
        audio = OggVorbis(path) if output_format == "ogg" else OggOpus(path)
        for key, value in _vorbis_comments(track, album_artist).items():
            audio[key] = value
        if cover:
            encoded = base64.b64encode(_flac_picture(cover).write()).decode("ascii")
            audio["METADATA_BLOCK_PICTURE"] = encoded
        audio.save()
        return

    if output_format == "m4a":
        audio = MP4(path)
        audio["\xa9nam"] = track.title
        audio["aART"] = album_artist
        if track.artist_name:
            audio["\xa9ART"] = track.artist_name
        if track.album_title:
            audio["\xa9alb"] = track.album_title
        if track.track_number:
            audio["trkn"] = [(track.track_number, 0)]
        if track.disc_number:
            audio["disk"] = [(track.disc_number, 0)]
        if track.release_year:
            audio["\xa9day"] = str(track.release_year)
        if track.genre:
            audio["\xa9gen"] = track.genre
        # Picard's MP4 mapping: iTunes freeform atoms.
        mbid_atoms = {
            "MusicBrainz Track Id": track.musicbrainz_id,
            "MusicBrainz Album Id": track.musicbrainz_release_id,
            "MusicBrainz Artist Id": track.musicbrainz_artist_id,
        }
        for name, value in mbid_atoms.items():
            if value:
                audio[f"----:com.apple.iTunes:{name}"] = MP4FreeForm(value.encode())
        if cover:
            image_format = (
                MP4Cover.FORMAT_PNG if _cover_mime(cover) == "image/png" else MP4Cover.FORMAT_JPEG
            )
            audio["covr"] = [MP4Cover(cover, imageformat=image_format)]
        audio.save()
        return

    raise ValueError(f"Unsupported output format for tagging: {output_format!r}")
