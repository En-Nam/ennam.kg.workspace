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

# service -> "context|dockerfile|extra-build-args"
build_one() {
  local name="$1" ctx="$2" dockerfile="$3" target="$4"
  echo ">> building ennam-kg-$name ($SHA / $VERSION)"
  docker build -f "$ctx/$dockerfile" ${target:+--target "$target"} \
    -t "ennam-kg-$name:$SHA" -t "ennam-kg-$name:$VERSION" -t "ennam-kg-$name:latest" \
    "$ctx"
}

push_one() {
  local name="$1"
  for t in "$SHA" "$VERSION" latest; do
    docker tag "ennam-kg-$name:$t" "$REGISTRY/ennam-kg-$name:$t"
    docker push "$REGISTRY/ennam-kg-$name:$t"
  done
}

build_one server    ennam.kg.go     deploy/docker/Dockerfile production
build_one python    ennam.kg.python Dockerfile               ""
build_one dashboard ennam.kg.next   Dockerfile               ""

if [ "$ACTION" = "push" ]; then
  for s in server python dashboard; do push_one "$s"; done
  echo ">> pushed to $REGISTRY — catalog:"
  curl -s "http://$REGISTRY/v2/_catalog" || true
fi
echo ">> done."
