"""
Batch 2 verification CLI — exercises the metadata resolution engine
standalone (grooverr.md Section 10, Batch 2: "a CLI script that takes a
query and prints resolved metadata is sufficient to verify this batch").

Usage:
  python resolve_cli.py track "Give Life Back to Music" --artist "Daft Punk"
  python resolve_cli.py album "Random Access Memories" --artist "Daft Punk"
  python resolve_cli.py artist "Daft Punk"
  python resolve_cli.py url "https://music.youtube.com/watch?v=..."
"""
import argparse
import asyncio
import json
import sys

from app.resolver import MetadataResolver


def _print(result) -> None:
    if result is None:
        print("No match found.")
        return
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))


async def main() -> int:
    parser = argparse.ArgumentParser(description="Grooverr metadata resolver CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_track = sub.add_parser("track", help="Resolve a track by title (+ optional artist/album)")
    p_track.add_argument("title")
    p_track.add_argument("--artist")
    p_track.add_argument("--album")

    p_album = sub.add_parser("album", help="Resolve an album by title (+ optional artist)")
    p_album.add_argument("title")
    p_album.add_argument("--artist")

    p_artist = sub.add_parser("artist", help="Resolve an artist by name")
    p_artist.add_argument("name")

    p_url = sub.add_parser("url", help="Detect + resolve a YouTube (Music) URL")
    p_url.add_argument("url")

    args = parser.parse_args()
    resolver = MetadataResolver()
    try:
        if args.command == "track":
            _print(await resolver.resolve_track(args.title, artist=args.artist, album=args.album))
        elif args.command == "album":
            _print(await resolver.resolve_album(args.title, artist=args.artist))
        elif args.command == "artist":
            _print(await resolver.resolve_artist(args.name))
        elif args.command == "url":
            result = await resolver.resolve_url(args.url)
            if result is None:
                print("Unrecognised or unresolvable URL.")
                return 1
            print(f"Detected type: {type(result).__name__.removeprefix('Resolved').lower()}")
            _print(result)
    finally:
        await resolver.close()
    return 0


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(asyncio.run(main()))
