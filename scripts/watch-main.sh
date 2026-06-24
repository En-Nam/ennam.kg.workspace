#!/usr/bin/env bash
# Local GitOps watcher: poll each sub-repo's origin/main and, when it advances,
# rebuild that service's image FROM origin/main (via `git archive` — no checkout,
# never touches your working tree) and redeploy the `daab` stack.
#
# This is the "commits land on main -> local Docker updates" trigger. Unlike the
# git hooks, it tracks the REMOTE main, not your local commits, and builds the
# exact code on main regardless of which branch your working tree is on.
#
# Usage:
#   scripts/watch-main.sh            # loop forever (Ctrl+C to stop)
#   scripts/watch-main.sh --once     # single pass (for cron / Task Scheduler)
#   WATCH_INTERVAL=30 scripts/watch-main.sh   # custom poll interval (s, default 60)
#
# Background it:  nohup bash scripts/watch-main.sh >> .watch-main.log 2>&1 &
set -uo pipefail
cd "$(dirname "$0")/.."                       # DAAB root
INTERVAL="${WATCH_INTERVAL:-60}"
VERSION="${VERSION:-v1.0.0}"
STATE_DIR=".deploy-state"; mkdir -p "$STATE_DIR"
COMPOSE=(docker compose -f docker-compose.release.yml)

# repo : service : dockerfile : target   (empty target = single-stage)
REPOS=(
  "ennam.kg.go:server:deploy/docker/Dockerfile:production"
  "ennam.kg.python:python:Dockerfile:"
  "ennam.kg.next:dashboard:Dockerfile:"
)

ts() { date +%H:%M:%S; }

build_if_changed() {  # repo svc dockerfile target  -> sets CHANGED=1 on (re)build
  local repo="$1" svc="$2" df="$3" target="$4"
  if ! git -C "$repo" fetch -q origin main 2>/dev/null; then
    echo "[$(ts)] $repo: fetch origin/main failed — skipping"; return 0
  fi
  local sha; sha="$(git -C "$repo" rev-parse origin/main 2>/dev/null)" || return 0
  local statef="$STATE_DIR/$svc" last=""
  [ -f "$statef" ] && last="$(cat "$statef")"
  [ "$sha" = "$last" ] && return 0           # main hasn't moved -> nothing to do

  local lastdisp="${last:0:7}"; [ -z "$lastdisp" ] && lastdisp="none"
  echo "[$(ts)] $repo origin/main $lastdisp -> ${sha:0:7} : building daab-$svc"
  # Build from origin/main with NO working-tree checkout: stream the tree as the
  # build context. Docker layer cache makes an unchanged build a fast no-op.
  if git -C "$repo" archive "$sha" \
       | docker build ${target:+--target "$target"} -f "$df" \
           -t "daab-$svc:$VERSION" -t "daab-$svc:latest" -t "daab-$svc:${sha:0:7}" - ; then
    echo "$sha" > "$statef"
    CHANGED=1
  else
    echo "[$(ts)] $repo: build failed — keeping previous daab-$svc image"
  fi
}

run_once() {
  CHANGED=0
  for entry in "${REPOS[@]}"; do
    IFS=: read -r repo svc df target <<< "$entry"
    build_if_changed "$repo" "$svc" "$df" "$target"
  done
  if [ "$CHANGED" = "1" ]; then
    echo "[$(ts)] >> redeploy daab stack (changed images)"
    "${COMPOSE[@]}" up -d
    echo "[$(ts)] >> deployed."
  fi
}

if [ "${1:-}" = "--once" ]; then run_once; exit 0; fi

echo "[$(ts)] watching origin/main of ${#REPOS[@]} sub-repos every ${INTERVAL}s (Ctrl+C to stop)"
while true; do run_once; sleep "$INTERVAL"; done
