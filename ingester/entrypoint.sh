#!/bin/sh
# Container entry point.
#   <image> ingest ...   -> python -m ingester   (data only: stage -> derive -> store)
#   <image> build ...    -> python -m pipeline   (the website build, unchanged)
# R2_PUSH=1 makes ingest publish to R2 (INGEST_STORE=r2) instead of the local store; credentials come from
# R2_*_FILE Docker secrets or R2_* variables at run time (compose.r2.yaml), never from the image.
set -eu

umask 0002
mkdir -p /output /app/data_cache "${HOME:-/tmp/snow-wx-home}" "${XDG_CACHE_HOME:-/tmp/snow-wx-cache}"

PYTHON=/opt/conda/envs/snow-wx/bin/python

if [ "${R2_PUSH:-0}" = "1" ]; then
  export INGEST_STORE=r2
fi

if [ "${1:-}" = "ingest" ]; then
  shift
  exec $PYTHON -m ingester "$@"
fi
exec $PYTHON -m pipeline "$@"
