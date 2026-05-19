#!/usr/bin/env bash
# Bootstrap: clone all Ennam KG sub-repos listed in scripts/repos.txt.
# Idempotent, best-effort. Re-running is safe.
# Spec: docs/superpowers/specs/2026-05-19-workspace-meta-repo-design.md
set -u

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root_dir="$(cd "$script_dir/.." && pwd)"
manifest="$script_dir/repos.txt"

if ! command -v git >/dev/null 2>&1; then
  echo "ERROR: git not found on PATH." >&2
  exit 1
fi
if [ ! -f "$manifest" ]; then
  echo "ERROR: manifest not found: $manifest" >&2
  exit 1
fi

cloned=0; skipped=0; failed=0

while IFS=$' \t\r' read -r dir url branch _rest || [ -n "${dir:-}" ]; do
  case "${dir:-}" in ''|'#'*) dir=""; continue ;; esac
  if [ -z "${url:-}" ]; then
    echo "WARN: bad manifest line for '$dir' (missing url), skipping" >&2
    failed=$((failed+1)); dir=""; continue
  fi
  branch="${branch:-main}"
  target="$root_dir/$dir"

  if [ -d "$target/.git" ]; then
    echo "skip   $dir (already a git repo)"
    skipped=$((skipped+1)); dir=""; continue
  fi
  if [ -e "$target" ]; then
    echo "FAIL   $dir (path exists but is not a git repo; not touching it)" >&2
    failed=$((failed+1)); dir=""; continue
  fi

  echo "clone  $dir <- $url ($branch)"
  if git clone -b "$branch" "$url" "$target"; then
    cloned=$((cloned+1))
  else
    echo "FAIL   $dir (git clone failed; check SSH access to GitHub En-Nam org)" >&2
    failed=$((failed+1))
  fi
  dir=""
done < "$manifest"

echo "----"
echo "summary: cloned=$cloned skipped=$skipped failed=$failed"
[ "$failed" -eq 0 ] || exit 1
