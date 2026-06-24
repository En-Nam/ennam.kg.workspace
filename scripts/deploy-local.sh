#!/usr/bin/env bash
# Local self-hosted auto-deploy: (re)build the given service's production image
# and redeploy the release stack via docker-compose.release.yml (ENVIRONMENT=
# selfhosted, AWS-free). `docker compose up -d` recreates only the containers
# whose image actually changed.
#
# Usage:
#   scripts/deploy-local.sh [server|python|dashboard|all]   # default: all
#
# Called automatically by the git hooks installed via install-deploy-hooks.sh,
# or run manually any time.
set -euo pipefail
cd "$(dirname "$0")/.."                       # DAAB root
SERVICE="${1:-all}"
VERSION="${VERSION:-v1.0.0}"
# Project/stack name comes from `name: daab` inside docker-compose.release.yml.
COMPOSE=(docker compose -f docker-compose.release.yml)
SHA="$(git -C ennam.kg.go rev-parse --short HEAD 2>/dev/null || echo local)"

build() {  # name context dockerfile target
  local name="$1" ctx="$2" dockerfile="$3" target="$4"
  echo ">> build ennam-kg-$name ($SHA)"
  docker build -f "$ctx/$dockerfile" ${target:+--target "$target"} \
    -t "ennam-kg-$name:$VERSION" -t "ennam-kg-$name:latest" -t "ennam-kg-$name:$SHA" "$ctx"
}

case "$SERVICE" in
  server)    build server    ennam.kg.go     deploy/docker/Dockerfile production ;;
  python)    build python    ennam.kg.python Dockerfile               "" ;;
  dashboard) build dashboard  ennam.kg.next   Dockerfile               "" ;;
  all)
    build server    ennam.kg.go     deploy/docker/Dockerfile production
    build python    ennam.kg.python Dockerfile               ""
    build dashboard ennam.kg.next   Dockerfile               "" ;;
  *) echo "usage: deploy-local.sh [server|python|dashboard|all]" >&2; exit 1 ;;
esac

echo ">> redeploy (selfhosted profile)"
"${COMPOSE[@]}" up -d
"${COMPOSE[@]}" ps
echo ">> deployed $SERVICE @ $SHA"
