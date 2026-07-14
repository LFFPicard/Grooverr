"""
Grooverr backend — FastAPI application entrypoint.

Batch 1: app boots, health check, DB init (WAL mode), serves built frontend.
Batch 4: queue worker pool runs inside this process (Section 9.3); SSE and
queue endpoints under /api/queue.
Batch 5: core REST API — search, library, settings, stats.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app import runtime
from app.api.activity import router as activity_router
from app.api.artists import router as artists_router
from app.api.library import router as library_router
from app.api.playlists import router as playlists_router
from app.api.search import router as search_router
from app.api.settings import router as settings_router
from app.api.stats import router as stats_router
from app.db import init_db
from app.queue import WorkerPool, hub
from app.queue.pipeline import Pipeline
from app.queue.routes import router as queue_router
from app.settings_store import get_setting

FRONTEND_DIST = os.environ.get("FRONTEND_DIST", "/app/frontend_dist")


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime.configure_logging()
    init_db()
    hub.bind_loop()
    # A user-configured MusicBrainz user-agent (Batch 8) must apply to the
    # process-wide client from the moment it starts serving requests.
    configured_ua = get_setting("musicbrainz_user_agent")
    if configured_ua:
        runtime.resolver.mb.set_user_agent(configured_ua)
    # Workers share the process-wide resolver (one MusicBrainz rate limiter).
    pool = WorkerPool(
        runtime.queue_service,
        pipeline=Pipeline(runtime.queue_service, resolver=runtime.resolver),
    )
    pool.start()
    try:
        yield
    finally:
        await pool.stop()


app = FastAPI(title="Grooverr", lifespan=lifespan)
app.include_router(queue_router)
app.include_router(search_router)
app.include_router(library_router)
app.include_router(artists_router)
app.include_router(settings_router)
app.include_router(stats_router)
app.include_router(activity_router)
app.include_router(playlists_router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "grooverr-backend"}


# Serve built frontend static assets if present (production container).
# In local dev, the Vite dev server handles the frontend separately.
if os.path.isdir(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")

    @app.get("/{full_path:path}")
    def spa_catch_all(full_path: str):
        index_path = os.path.join(FRONTEND_DIST, "index.html")
        return FileResponse(index_path)
