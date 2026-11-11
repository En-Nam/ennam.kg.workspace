#!/bin/sh
# Compose init wrapper (runs once on a fresh postgres volume): feeds the
# LANDED_*_PASSWORD env vars to init.sql as psql variables.
set -eu
: "${LANDED_MAINT_PASSWORD:?LANDED_MAINT_PASSWORD required}"
: "${LANDED_WRITER_PASSWORD:?LANDED_WRITER_PASSWORD required}"
: "${LANDED_ENGINE_PASSWORD:?LANDED_ENGINE_PASSWORD required}"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v maint_pw="$LANDED_MAINT_PASSWORD" -v writer_pw="$LANDED_WRITER_PASSWORD" -v engine_pw="$LANDED_ENGINE_PASSWORD" \
  -f /landed/init.sql
