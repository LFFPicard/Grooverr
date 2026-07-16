"""
Version endpoint (Section 8 Settings footer; Batch 9 packaging scope;
Section 11 item 19).

Reads a small JSON file baked into the image at Docker build time — never
computed at runtime, since a runtime-computed value would show the same
thing regardless of what commit was actually built. Found necessary after
real debugging time was lost more than once to not being able to tell
whether a running container was actually on a given fix.
"""
import json
import os

from fastapi import APIRouter

from app.api.schemas import VersionOut

router = APIRouter(prefix="/api", tags=["version"])

VERSION_FILE = os.environ.get("VERSION_FILE", "/app/version.json")


@router.get("/version", response_model=VersionOut)
def get_version():
    try:
        with open(VERSION_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return VersionOut(git_sha=data.get("git_sha") or "unknown", build_date=data.get("build_date"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        # Local dev / no Docker build ever ran here — not a real build, so
        # say so plainly rather than fabricating a value.
        return VersionOut(git_sha="dev", build_date=None)
