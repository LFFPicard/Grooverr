"""
Grooverr backend — FastAPI application entrypoint.
Batch 1 scope: app boots, health check, DB initializes with WAL mode,
serves the built frontend as static files.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.db import init_db

FRONTEND_DIST = os.environ.get("FRONTEND_DIST", "/app/frontend_dist")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Grooverr", lifespan=lifespan)


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
