#!/bin/sh
# Reconciles the app user to the requested PUID/PGID (LinuxServer.io /
# Unraid convention) before dropping from root to run the actual app —
# so files Grooverr writes into bind-mounted /music and /config land with
# ownership the host user can actually manage, rather than root:root.
set -e

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if [ "$(id -u)" = "0" ]; then
    current_gid="$(getent group grooverr | cut -d: -f3)"
    if [ "$current_gid" != "$PGID" ]; then
        groupmod -o -g "$PGID" grooverr
    fi
    current_uid="$(id -u grooverr)"
    if [ "$current_uid" != "$PUID" ]; then
        usermod -o -u "$PUID" grooverr
    fi

    mkdir -p "${CONFIG_DIR:-/config}" "${MUSIC_DIR:-/music}"
    # /config is small and entirely Grooverr-owned data — always reconciled.
    chown -R grooverr:grooverr "${CONFIG_DIR:-/config}"
    # /music can be a large pre-existing library — only the mount point
    # itself is touched; PUID/PGID is expected to already have write
    # access to whatever's inside (same assumption every LSIO image makes).
    chown grooverr:grooverr "${MUSIC_DIR:-/music}" 2>/dev/null || true

    echo "Starting Grooverr as UID=$PUID GID=$PGID"
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$0" "$@"
fi

exec "$@"
