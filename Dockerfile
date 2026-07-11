# Grooverr — multi-stage build
# Stage 1: build the React frontend
# Stage 2: Python backend serving the built frontend as static files

FROM node:20-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS backend

LABEL maintainer="LFFPicard"
LABEL description="Grooverr — self-hosted music acquisition and library manager"
LABEL org.opencontainers.image.source="https://github.com/LFFPicard/Grooverr"

WORKDIR /app

# System deps needed later for audio download/conversion (ffmpeg) — included
# now so later batches don't need a Dockerfile rebuild of this base layer.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
  && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=frontend-build /frontend/dist ./frontend_dist

VOLUME /music
VOLUME /config

ENV CONFIG_DIR=/config
ENV MUSIC_DIR=/music
ENV FRONTEND_DIST=/app/frontend_dist
ENV PORT=8000

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
