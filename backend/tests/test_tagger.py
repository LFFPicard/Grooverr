"""
Tagging tests — generate real (silent) audio files with ffmpeg for every
supported output format, embed the full Section 6 tag set + cover art,
then read the tags back off disk and verify them. No network.
"""
import base64
import subprocess

import pytest

from app.downloader.tagger import embed_tags
from app.downloader.ytdlp import SUPPORTED_FORMATS, resolve_ffmpeg_path
from app.resolver.schemas import MetadataSource, ResolvedTrack

# 1×1 transparent PNG.
COVER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

TRACK = ResolvedTrack(
    title="Test Title",
    artist_name="Test Artist",
    album_title="Test Album",
    track_number=3,
    disc_number=2,
    release_year=2013,
    genre="electronic",
    musicbrainz_id="rec-mbid",
    musicbrainz_release_id="rel-mbid",
    musicbrainz_artist_id="artist-mbid",
    source=MetadataSource.musicbrainz,
)

_ENCODER = {
    "mp3": "libmp3lame",
    "flac": "flac",
    "m4a": "aac",
    "opus": "libopus",
    "wav": "pcm_s16le",
    "ogg": "libvorbis",
}


@pytest.fixture(scope="module")
def ffmpeg():
    path = resolve_ffmpeg_path()
    if not path:
        pytest.skip("no ffmpeg available")
    return path


def make_silent_file(ffmpeg, directory, fmt):
    out = directory / f"silent.{fmt}"
    subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
         "-t", "0.3", "-c:a", _ENCODER[fmt], str(out)],
        check=True, capture_output=True,
    )
    return out


@pytest.mark.parametrize("fmt", SUPPORTED_FORMATS)
def test_roundtrip_all_formats(ffmpeg, tmp_path, fmt):
    path = make_silent_file(ffmpeg, tmp_path, fmt)
    embed_tags(path, fmt, TRACK, album_artist="Test Album Artist", cover=COVER_PNG)

    import mutagen
    audio = mutagen.File(path)
    assert audio is not None and audio.tags is not None

    if fmt in ("mp3", "wav"):
        tags = audio.tags
        assert str(tags["TIT2"]) == "Test Title"
        assert str(tags["TPE1"]) == "Test Artist"
        assert str(tags["TPE2"]) == "Test Album Artist"
        assert str(tags["TALB"]) == "Test Album"
        assert str(tags["TRCK"]) == "3"
        assert str(tags["TPOS"]) == "2"
        assert str(tags["TDRC"]) == "2013"
        assert str(tags["TCON"]) == "electronic"
        assert tags["UFID:http://musicbrainz.org"].data == b"rec-mbid"
        assert str(tags["TXXX:MusicBrainz Album Id"]) == "rel-mbid"
        assert str(tags["TXXX:MusicBrainz Artist Id"]) == "artist-mbid"
        apic = tags.getall("APIC")
        assert len(apic) == 1 and apic[0].data == COVER_PNG
        assert apic[0].mime == "image/png"
    elif fmt in ("flac", "ogg", "opus"):
        assert audio["TITLE"] == ["Test Title"]
        assert audio["ARTIST"] == ["Test Artist"]
        assert audio["ALBUMARTIST"] == ["Test Album Artist"]
        assert audio["ALBUM"] == ["Test Album"]
        assert audio["TRACKNUMBER"] == ["3"]
        assert audio["DISCNUMBER"] == ["2"]
        assert audio["DATE"] == ["2013"]
        assert audio["GENRE"] == ["electronic"]
        assert audio["MUSICBRAINZ_TRACKID"] == ["rec-mbid"]
        assert audio["MUSICBRAINZ_ALBUMID"] == ["rel-mbid"]
        assert audio["MUSICBRAINZ_ARTISTID"] == ["artist-mbid"]
        if fmt == "flac":
            assert len(audio.pictures) == 1 and audio.pictures[0].data == COVER_PNG
        else:
            from mutagen.flac import Picture
            block = base64.b64decode(audio["METADATA_BLOCK_PICTURE"][0])
            assert Picture(block).data == COVER_PNG
    else:  # m4a
        assert audio["\xa9nam"] == ["Test Title"]
        assert audio["\xa9ART"] == ["Test Artist"]
        assert audio["aART"] == ["Test Album Artist"]
        assert audio["\xa9alb"] == ["Test Album"]
        assert audio["trkn"] == [(3, 0)]
        assert audio["disk"] == [(2, 0)]
        assert audio["\xa9day"] == ["2013"]
        assert audio["\xa9gen"] == ["electronic"]
        assert bytes(audio["----:com.apple.iTunes:MusicBrainz Track Id"][0]) == b"rec-mbid"
        assert bytes(audio["----:com.apple.iTunes:MusicBrainz Album Id"][0]) == b"rel-mbid"
        assert bytes(audio["----:com.apple.iTunes:MusicBrainz Artist Id"][0]) == b"artist-mbid"
        assert bytes(audio["covr"][0]) == COVER_PNG


def test_sparse_metadata_never_raises(ffmpeg, tmp_path):
    """A track with almost everything missing must still tag cleanly."""
    sparse = ResolvedTrack(title="Only a Title", source=MetadataSource.youtube_music)
    for fmt in ("mp3", "flac"):
        path = make_silent_file(ffmpeg, tmp_path, fmt)
        embed_tags(path, fmt, sparse, cover=None)
        import mutagen
        audio = mutagen.File(path)
        if fmt == "mp3":
            assert str(audio.tags["TIT2"]) == "Only a Title"
            assert "TXXX:MusicBrainz Album Id" not in audio.tags
        else:
            assert audio["TITLE"] == ["Only a Title"]
