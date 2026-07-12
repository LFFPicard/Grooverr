"""
Grooverr backend — FastAPI application entrypoint.

Batch 1: app boots, health check, DB init (WAL mode), serves built frontend.
Batch 4: queue worker pool runs inside this process (Section 9.3); SSE and
queue endpoints under /api/queue.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.db import init_db
from app.queue import QueueService, WorkerPool, hub
from app.queue.routes import router as queue_router

FRONTEND_DIST = os.environ.get("FRONTEND_DIST", "/app/frontend_dist")

# Process-wide queue service; the worker pool is created per app lifespan.
queue_service = QueueService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    hub.bind_loop()
    pool = WorkerPool(queue_service)
    pool.start()
    try:
        yield
    finally:
        await pool.stop()


app = FastAPI(title="Grooverr", lifespan=lifespan)
app.include_router(queue_router)


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
