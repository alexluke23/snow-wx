#!/bin/sh
# Container entry point: runs the ingester (python -m ingester). Arguments are the CLI's, e.g. `ingest run asos`.
#
# Docker creates a missing bind-mount folder as root, so the container first gives the mounted output and cache folders
# to LOCAL_UID:LOCAL_GID (your user), then re-runs this script as that user. Nothing else runs as root.
# R2_PUSH=1 (the compose default) publishes to R2 (INGEST_STORE=r2); R2_PUSH=0 writes the local store only. Credentials come
# from R2_*_FILE Docker secrets or R2_* variables at run time (compose.yaml), never from the image.
set -eu

LOCAL_UID="${LOCAL_UID:-1000}"
LOCAL_GID="${LOCAL_GID:-1000}"

if [ "$(id -u)" = "0" ]; then
  mkdir -p /app/data_cache
  for d in /launch/output /app/data_cache; do
    if [ -d "$d" ] && [ "$(stat -c '%u:%g' "$d")" != "$LOCAL_UID:$LOCAL_GID" ]; then
      chown "$LOCAL_UID:$LOCAL_GID" "$d"
    fi
  done
  exec setpriv --reuid="$LOCAL_UID" --regid="$LOCAL_GID" --clear-groups "$0" "$@"
fi

umask 0002
mkdir -p "${HOME:-/tmp/snow-wx-home}" "${XDG_CACHE_HOME:-/tmp/snow-wx-cache}"

PYTHON=/opt/conda/envs/ingester/bin/python

if [ "${R2_PUSH:-0}" = "1" ]; then
  export INGEST_STORE=r2
fi

if [ "${1:-}" = "ingest" ]; then
  shift
fi
exec $PYTHON -m ingester "$@"
