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
# curl: HEALTHCHECK probe
# util-linux (setpriv) ships in the base slim image already — entrypoint.sh
#       uses it to drop from root to the PUID/PGID-mapped app user
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    tini \
    curl \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

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
