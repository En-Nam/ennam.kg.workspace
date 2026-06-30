#!/usr/bin/env bash
# Upload a markdown file into Ennam KG (Phase 6 Sprint 2+3).
#
# Usage:
#   ./scripts/ingest-md-via-api.sh path/to/report.md
#   ./scripts/ingest-md-via-api.sh path/to/report.md --process
#
# Env: API_URL (default http://127.0.0.1:8080), API_KEY, PROJECT_ID

set -euo pipefail

API_URL="${API_URL:-http://127.0.0.1:8080}"
API_KEY="${API_KEY:-ennam_kg_dev_000000000000000000000000}"
PROJECT_ID="${PROJECT_ID:-b0000000-0000-0000-0000-000000000010}"

FILE="${1:-}"
PROCESS=false
shift || true
for arg in "$@"; do
  if [[ "$arg" == "--process" ]]; then
    PROCESS=true
  fi
done

if [[ -z "$FILE" || ! -f "$FILE" ]]; then
  echo "Usage: $0 <file.md> [--process]" >&2
  exit 1
fi

SOURCE_ID="${SOURCE_ID:-upload:$(basename "$FILE")}"
TITLE="${TITLE:-$(basename "$FILE")}"

RESP=$(curl -s -w "\n%{http_code}" \
  -H "Authorization: Bearer ${API_KEY}" \
  -F "file=@${FILE}" \
  -F "title=${TITLE}" \
  -F "source_id=${SOURCE_ID}" \
  -F "auto_approve=true" \
  "${API_URL}/api/v1/projects/${PROJECT_ID}/ingest/upload")

HTTP_CODE=$(echo "$RESP" | tail -n1)
BODY=$(echo "$RESP" | sed '$d')

echo "$BODY" | python3 -m json.tool 2>/dev/null || echo "$BODY"
echo "HTTP ${HTTP_CODE}"

if [[ "$HTTP_CODE" != "200" && "$HTTP_CODE" != "201" ]]; then
  exit 1
fi

if [[ "$PROCESS" == "true" ]]; then
  DRAFT_ID=$(echo "$BODY" | python3 -c "import json,sys; print(json.load(sys.stdin).get('draft_id',''))")
  if [[ -z "$DRAFT_ID" ]]; then
    echo "Could not read draft_id from response" >&2
    exit 1
  fi
  echo "Processing draft ${DRAFT_ID} (structured, async)..."
  curl -s \
    -H "Authorization: Bearer ${API_KEY}" \
    -X POST \
    "${API_URL}/api/v1/projects/${PROJECT_ID}/draft-nodes/${DRAFT_ID}/process" \
    | python3 -m json.tool

  echo "Waiting for worker (up to 90s)..."
  for _ in $(seq 1 30); do
    STATUS=$(curl -s \
      -H "Authorization: Bearer ${API_KEY}" \
      "${API_URL}/api/v1/projects/${PROJECT_ID}/draft-nodes/${DRAFT_ID}" \
      | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))")
    echo "  status=${STATUS}"
    if [[ "${STATUS}" == "processed" ]]; then
      curl -s \
        -H "Authorization: Bearer ${API_KEY}" \
        "${API_URL}/api/v1/projects/${PROJECT_ID}/draft-nodes/${DRAFT_ID}" \
        | python3 -m json.tool
      break
    fi
    if [[ "${STATUS}" == "failed" ]]; then
      echo "Draft processing failed" >&2
      exit 1
    fi
    sleep 3
  done
fi
