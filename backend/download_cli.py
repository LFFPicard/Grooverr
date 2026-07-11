"""
Batch 3 verification CLI — resolves a track (Batch 2 engine), finds its
audio source, downloads, tags and places it, then reads the tags back off
the finished file so correctness is inspected directly (per the Batch 3
Definition of Done).

Usage:
  python download_cli.py "Give Life Back to Music" --artist "Daft Punk" \
      --album "Random Access Memories" --format mp3 --quality 192 \
      --music-root ./music [--multi-disc]
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.downloader import DownloadEngine, DownloadFailure
from app.resolver import MetadataResolver


def dump_tags(path: Path) -> dict:
    """Read every tag straight back off the finished file."""
    import mutagen
    audio = mutagen.File(path)
    tags = {}
    for key, value in dict(audio.tags or {}).items():
        text = str(value)
        tags[str(key)] = text if len(text) < 120 else f"<{len(text)} bytes>"
    info = audio.info
    return {
        "tags": tags,
        "length_seconds": round(getattr(info, "length", 0), 1),
        "bitrate": getattr(info, "bitrate", None),
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description="Grooverr download engine CLI")
    parser.add_argument("title")
    parser.add_argument("--artist")
    parser.add_argument("--album")
    parser.add_argument("--format", default="mp3", dest="output_format")
    parser.add_argument("--quality", type=int, default=None, help="bitrate ceiling in kbps")
    parser.add_argument("--music-root", default="./music")
    parser.add_argument("--multi-disc", action="store_true", default=None,
                        help="album has more than one disc (enables the disc-number prefix)")
    args = parser.parse_args()

    resolver = MetadataResolver()
    try:
        track = await resolver.resolve_track(args.title, artist=args.artist, album=args.album)
    finally:
        await resolver.close()
    if track is None:
        print("Metadata resolution found no match.")
        return 1
    print("Resolved metadata:")
    print(json.dumps(track.model_dump(mode="json"), indent=2, ensure_ascii=False))

    engine = DownloadEngine(music_root=args.music_root, ytmusic=resolver.yt)
    try:
        result = await engine.download_track(
            track,
            output_format=args.output_format,
            quality_kbps=args.quality,
            multi_disc=args.multi_disc,
        )
    except DownloadFailure as exc:
        print(f"Download failed: {exc}")
        return 1

    print("\nDownload result:")
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
    print("\nTags read back from the finished file:")
    print(json.dumps(dump_tags(Path(result.file_path)), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(asyncio.run(main()))
