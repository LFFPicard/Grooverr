"""Section 6 naming/folder convention tests — pure logic, no network."""
import pytest

from app.downloader.paths import render_track_path, sanitize_component


def test_default_template_single_disc():
    # Spec example: /music/Daft Punk/Random Access Memories (2013)/01 - Give Life Back to Music.flac
    path = render_track_path(
        music_root="/music",
        title="Give Life Back to Music",
        album_artist="Daft Punk",
        album="Random Access Memories",
        ext="flac",
        track_number=1,
        disc_number=1,
        release_year=2013,
        multi_disc=False,
    )
    assert path.as_posix() == "/music/Daft Punk/Random Access Memories (2013)/01 - Give Life Back to Music.flac"


def test_multi_disc_prefix_appears():
    # Spec example: /music/Arcade Fire/Reflektor (2013)/2-03 - Supersymmetry.mp3
    path = render_track_path(
        music_root="/music",
        title="Supersymmetry",
        album_artist="Arcade Fire",
        album="Reflektor",
        ext="mp3",
        track_number=3,
        disc_number=2,
        release_year=2013,
        multi_disc=True,
    )
    assert path.as_posix() == "/music/Arcade Fire/Reflektor (2013)/2-03 - Supersymmetry.mp3"


def test_disc_prefix_absent_on_single_disc_album():
    path = render_track_path(
        music_root="/music", title="T", album_artist="A", album="B",
        ext="mp3", track_number=3, disc_number=1, release_year=2000,
        multi_disc=False,
    )
    assert "1-" not in path.name
    assert path.name == "03 - T.mp3"


def test_disc_prefix_on_disc_one_of_multi_disc_album():
    # Spec example shows 1-01 for disc 1 of a multi-disc album.
    path = render_track_path(
        music_root="/music", title="Reflektor", album_artist="Arcade Fire",
        album="Reflektor", ext="mp3", track_number=1, disc_number=1,
        release_year=2013, multi_disc=True,
    )
    assert path.name == "1-01 - Reflektor.mp3"


def test_track_number_zero_padded():
    path = render_track_path(
        music_root="/m", title="T", album_artist="A", album="B",
        ext="mp3", track_number=7, release_year=2000,
    )
    assert path.name == "07 - T.mp3"


def test_illegal_characters_replaced():
    path = render_track_path(
        music_root="/music",
        title='What "Is" This? A/B <Test>: 50|50 *',
        album_artist="AC/DC",
        album="Back\\Slash: The Album",
        ext="mp3",
        track_number=1,
        release_year=1980,
    )
    parts = path.as_posix().split("/")
    assert parts[2] == "AC-DC"                       # no extra folder created
    assert parts[3] == "Back-Slash- The Album (1980)"
    assert path.name == "01 - What -Is- This- A-B -Test-- 50-50 -.mp3"


def test_missing_year_drops_parenthetical():
    path = render_track_path(
        music_root="/music", title="T", album_artist="A", album="B",
        ext="mp3", track_number=1, release_year=None,
    )
    assert path.as_posix() == "/music/A/B/01 - T.mp3"


def test_missing_fields_get_placeholders():
    path = render_track_path(
        music_root="/m", title="", album_artist="", album="", ext="mp3",
    )
    assert path.as_posix() == "/m/Unknown Artist/Unknown Album/00 - Unknown Title.mp3"


def test_unknown_template_token_raises():
    with pytest.raises(ValueError, match="Bogus"):
        render_track_path(
            music_root="/m", title="T", album_artist="A", album="B", ext="mp3",
            template="{MusicRoot}/{Bogus}/{Title}.{ext}",
        )


def test_sanitize_component():
    assert sanitize_component("AC/DC") == "AC-DC"
    assert sanitize_component("dots and spaces.  ") == "dots and spaces"
    assert sanitize_component("a  lot   of\tspace") == "a lot of space"
    assert sanitize_component('<>:"/\\|?*') == "-" * 9
    assert sanitize_component("...") == "_"        # never an empty component
