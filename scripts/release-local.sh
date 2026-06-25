#!/usr/bin/env bash
# Local-Docker release pipeline for all three DAAB services.
# Builds production images, tags them (SHA + semver + latest), and optionally
# pushes to a local registry (registry:2) — no AWS / ECR required.
#
# Usage:
#   scripts/release-local.sh build                 # build + tag locally only
#   scripts/release-local.sh push                  # build + tag + push to $REGISTRY
#   REGISTRY=localhost:5000 VERSION=v1.0.1 scripts/release-local.sh push
#
# Env:
#   VERSION   semver tag (default v1.0.0)
#   REGISTRY  registry host:port for `push` (default localhost:5000)
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="${VERSION:-v1.0.0}"
REGISTRY="${REGISTRY:-localhost:5000}"
ACTION="${1:-build}"
SHA="$(git -C ennam.kg.go rev-parse --short HEAD)"

# Load .env (if present) so build args (e.g. the dashboard's NEXT_PUBLIC_SUPABASE_*)
# come from there instead of being hardcoded. Empty when unset = feature disabled.
set -a; [ -f .env ] && . ./.env; set +a

# build_one NAME CTX DOCKERFILE TARGET [extra docker-build args...]
build_one() {
  local name="$1" ctx="$2" dockerfile="$3" target="$4"; shift 4
  echo ">> building daab-$name ($SHA / $VERSION)"
  docker build -f "$ctx/$dockerfile" ${target:+--target "$target"} "$@" \
    -t "daab-$name:$SHA" -t "daab-$name:$VERSION" -t "daab-$name:latest" \
    "$ctx"
}

push_one() {
  local name="$1"
  for t in "$SHA" "$VERSION" latest; do
    docker tag "daab-$name:$t" "$REGISTRY/daab-$name:$t"
    docker push "$REGISTRY/daab-$name:$t"
  done
}

build_one server    ennam.kg.go     deploy/docker/Dockerfile production
build_one python    ennam.kg.python Dockerfile               ""
# Dashboard: NEXT_PUBLIC_* are baked at build time (Next.js), so pass them as
# build args (sourced from .env above; empty => Supabase login disabled).
build_one dashboard ennam.kg.next   Dockerfile               "" \
  --build-arg "NEXT_PUBLIC_SUPABASE_URL=${NEXT_PUBLIC_SUPABASE_URL:-}" \
  --build-arg "NEXT_PUBLIC_SUPABASE_ANON_KEY=${NEXT_PUBLIC_SUPABASE_ANON_KEY:-}"

if [ "$ACTION" = "push" ]; then
  for s in server python dashboard; do push_one "$s"; done
  echo ">> pushed to $REGISTRY — catalog:"
  curl -s "http://$REGISTRY/v2/_catalog" || true
fi
echo ">> done."
