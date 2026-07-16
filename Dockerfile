# Grooverr — multi-stage build
# Stage 1: build the React frontend
# Stage 2: Python backend serving the built frontend as static files

FROM node:20-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS backend

LABEL maintainer="LFFPicard"
LABEL description="Grooverr — self-hosted music acquisition and library manager"
LABEL org.opencontainers.image.source="https://github.com/LFFPicard/Grooverr"

WORKDIR /app

# ffmpeg: audio conversion (Section 6, all 6 output formats)
# tini: PID 1 with correct signal handling, so SIGTERM reaches uvicorn and
#       the asyncio workers cleanly (Section 9.3 — a killed container must
#       resume cleanly on restart, not leave orphaned ffmpeg/yt-dlp processes)
# curl: HEALTHCHECK probe, also fetches the deno installer below
# unzip: required by deno's official install script
# util-linux (setpriv) ships in the base slim image already — entrypoint.sh
#       uses it to drop from root to the PUID/PGID-mapped app user
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    tini \
    curl \
    unzip \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# yt-dlp JS runtime (Section 11 item 17): without one, yt-dlp can't solve
# YouTube's signature/n-parameter JS challenges and silently loses access to
# some formats (yt-dlp's own warning: "some formats may be missing"). NOTE:
# this is NOT the same thing as PO-token support — PO tokens are a separate
# yt-dlp subsystem (bgutil-ytdlp-pot-provider plugin) not covered by a JS
# runtime alone, and per yt-dlp's PO Token Guide, the android_vr client this
# app's downloads land on doesn't require them anyway. Installed to
# /usr/local/bin so it's on PATH for the PUID/PGID-remapped non-root runtime
# user too (no per-user $HOME install).
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh

# Non-root by default — entrypoint.sh remaps this to PUID/PGID at container
# start (Unraid/LinuxServer.io convention), default 1000:1000 if unset.
RUN groupadd -g 1000 grooverr \
  && useradd -u 1000 -g grooverr -M -s /usr/sbin/nologin grooverr

COPY backend/requirements.txt .
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.txt

COPY backend/app ./app
COPY --from=frontend-build /frontend/dist ./frontend_dist
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Version footer (Section 8 Settings screen, Batch 9, Section 11 item 19):
# baked in at build time from build args, never computed at container
# runtime — a runtime-computed value would show the same thing regardless
# of what commit was actually built, defeating the entire point ("is this
# container actually running the fix I think it's running"). Kept as the
# last layer before the volumes so a per-commit SHA change doesn't bust the
# cache for the expensive layers above it (apt/deno/pip/npm).
ARG GIT_SHA=unknown
ARG BUILD_DATE=unknown
RUN printf '{"git_sha":"%s","build_date":"%s"}' "$GIT_SHA" "$BUILD_DATE" > /app/version.json

VOLUME /music
VOLUME /config

ENV CONFIG_DIR=/config
ENV MUSIC_DIR=/music
ENV FRONTEND_DIST=/app/frontend_dist
ENV PORT=8000
ENV PUID=1000
ENV PGID=1000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

ENTRYPOINT ["tini", "--", "/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
