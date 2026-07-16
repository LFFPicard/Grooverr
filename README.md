# Grooverr

"Point it at the music. Get a library."

Grooverr is a self-hosted music acquisition and library manager. Search for a
track, album, artist, or paste a YouTube Music playlist link. Grooverr
resolves canonical metadata via MusicBrainz, downloads audio via YouTube
Music, converts it to your chosen format, tags it with Picard-compatible
metadata and embedded cover art, and files it into your library using a
clean, predictable naming convention that Plex, Navidrome, Jellyfin, or any
scraper can read without further massaging.

Single-user, no accounts, no Spotify dependency.

## Requirements

- Docker (or a Docker-compatible host, e.g. Unraid)
- Two persistent locations: one for your music library, one for Grooverr's
  own config/database

## Quick start — Docker

```bash
docker run -d \
  --name grooverr \
  -p 8000:8000 \
  -e PUID=1000 \
  -e PGID=1000 \
  -v /path/to/your/music:/music \
  -v /path/to/appdata/grooverr:/config \
  --restart unless-stopped \
  lffpicard/grooverr:latest
```

Then open `http://<host>:8000`.

## Docker Compose

```bash
git clone https://github.com/LFFPicard/Grooverr.git
cd Grooverr
docker compose up -d
```

Edit the `volumes:` section of `docker-compose.yml` first — the checked-in
paths (`/path/to/your/music`, `/path/to/appdata/Grooverr`) are placeholders.

## Unraid (Community Applications)

1. In the CA app store, search for **Grooverr**. (Until the template is
   accepted into the official CA index, add it manually: **Apps → Template
   URL**, paste
   `https://raw.githubusercontent.com/LFFPicard/Grooverr/master/unraid/grooverr.xml`.)
2. Set **Music** to your existing music share (e.g. `/mnt/user/music/`).
3. Set **Config** to a dedicated appdata folder (e.g.
   `/mnt/user/appdata/grooverr/`) — never point this at the same path as
   Music.
4. Leave **PUID**/**PGID** at the defaults (`99`/`100`, Unraid's `nobody`/
   `users`) unless your library is owned by a different user.
5. Apply, then open the WebUI from the Docker tab.

## First-time setup

Open **Settings** in the web UI and configure:

- MusicBrainz user-agent string (no API key needed, but MusicBrainz
  rate-limits by user-agent)
- Optional YouTube cookie file, if you hit YouTube rate limits or need
  access to age-restricted content
- Default quality ceiling
- Output path template

Then use **Search** to find a track, album, artist, or paste a YouTube Music
playlist link, and add it to your library. Progress is visible live on the
**Dashboard** and **Queue** screens.

## Configuration reference

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `PUID` | `1000` | User ID Grooverr runs as, so files written to `/music` and `/config` are owned by a user you can manage |
| `PGID` | `1000` | Group ID Grooverr runs as |
| `PORT` | `8000` | Port the web server listens on inside the container |

### Volumes

| Container path | Purpose |
|---|---|
| `/music` | Your music library. Grooverr reads what's already there to skip duplicates, and writes newly downloaded albums/tracks here. |
| `/config` | Grooverr's own database, settings, and optional YouTube cookies file. Keep this separate from `/music`. |

The container runs as a non-root user by default, dropping from root to the
`PUID`/`PGID`-mapped user at startup (same convention used by LinuxServer.io
images), and exposes a `/api/health` endpoint used by the built-in Docker
`HEALTHCHECK`.

## Building from source

```bash
git clone https://github.com/LFFPicard/Grooverr.git
cd Grooverr
docker build -t grooverr:local .
```

The image is a multi-stage build: the React frontend is built in a Node
stage and only its static output is copied into the final Python/FastAPI
image, so Node tooling never ships in the final image.

## Contributing / CI

Pushes to `main` automatically build and publish `lffpicard/grooverr:latest`
to Docker Hub via GitHub Actions (`.github/workflows/docker-publish.yml`).
To run this workflow in a fork, set these repository secrets:

| Secret | Description |
|---|---|
| `DOCKERHUB_USERNAME` | Docker Hub account/organization to publish under |
| `DOCKERHUB_TOKEN` | Docker Hub access token (Account Settings → Security → Access Tokens) |

## License

TBD.
