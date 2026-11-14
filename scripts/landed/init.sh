#!/bin/sh
# Compose init wrapper (runs once on a fresh postgres volume). init.sql reads the
# LANDED_*_PASSWORD env vars itself (psql \getenv); this only fails fast if unset.
set -eu
: "${LANDED_MAINT_PASSWORD:?LANDED_MAINT_PASSWORD required}"
: "${LANDED_WRITER_PASSWORD:?LANDED_WRITER_PASSWORD required}"
: "${LANDED_ENGINE_PASSWORD:?LANDED_ENGINE_PASSWORD required}"
: "${LANDED_AI_PASSWORD:?LANDED_AI_PASSWORD required}"
exec psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f /landed/init.sql
