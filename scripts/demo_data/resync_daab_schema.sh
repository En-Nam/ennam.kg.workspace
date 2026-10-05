#!/usr/bin/env bash
# After load_pharmacy_demo.sh: refresh DAAB's view of the Pharmacy POS DB data source.
# Order matters (checkpoint 2026-08-17): extract-schema -> sync-schema -> generate-kg.
# sync-schema alone only refreshes source_tables metadata; KG nodes public.<table> come from generate-kg.
# Env: DAAB_API_KEY (required, developer role on the project), DAAB_API_URL (default: localhost + KG_SERVER_PORT
#      from the workspace .env, else 8082), PHARMACY_DATA_SOURCE_ID, PHARMACY_PROJECT_ID, DAAB_PG_CONTAINER,
#      EXPECTED_TABLES (default 25).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# kg-server's host port comes from KG_SERVER_PORT in the workspace .env (8082 on the dev machine; 8080 is
# only the container-internal port and may belong to an unrelated app on the host).
if [ -z "${KG_SERVER_PORT:-}" ] && [ -f "$ROOT/.env" ]; then
  KG_SERVER_PORT="$(grep -E '^KG_SERVER_PORT=' "$ROOT/.env" | tail -1 | cut -d= -f2)"
fi
API="${DAAB_API_URL:-http://localhost:${KG_SERVER_PORT:-8082}}"
curl -fsS "$API/healthz" > /dev/null || { echo "kg-server not reachable at $API (set DAAB_API_URL)" >&2; exit 1; }
KEY="${DAAB_API_KEY:?set DAAB_API_KEY (API key with developer role on the pharmacy project)}"
DS="${PHARMACY_DATA_SOURCE_ID:-3c7af733-b069-4654-b98e-beb5afde588c}"
PROJECT="${PHARMACY_PROJECT_ID:-4ad7a5fa-a036-4f6a-8229-39a20af23e38}"
CONTAINER="${DAAB_PG_CONTAINER:-daab-postgres}"
EXPECTED_TABLES="${EXPECTED_TABLES:-25}"

post() {
  curl -fsS -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -d "$2" "$API$1" > /dev/null
}

list_jobs() { curl -fsS -H "Authorization: Bearer $KEY" "$API/api/v1/data-sources/$DS/sync-jobs"; }

wait_job() {  # $1 = job_type (schema_extraction | schema_sync | kg_generation), $2 = JSON array of job ids seen before
  local status="none"
  for _ in $(seq 1 120); do
    status="$(list_jobs | jq -r --arg t "$1" --argjson seen "$2" \
      '[.[] | select(.job_type == $t and ((.id as $i | $seen | index($i)) == null))][0].status // "none"')"
    case "$status" in
      completed) echo "$1 completed"; return 0 ;;
      failed) echo "$1 failed" >&2; return 1 ;;
    esac
    sleep 5
  done
  echo "$1 did not finish (last status: $status)" >&2
  return 1
}

seen="$(list_jobs | jq -c '[.[].id]')"
post "/api/v1/data-sources/$DS/extract-schema" '{"created_by":"pi-plan-a"}'
wait_job schema_extraction "$seen"
post "/api/v1/data-sources/$DS/sync-schema" '{"created_by":"pi-plan-a"}'
wait_job schema_sync "$seen"
post "/api/v1/data-sources/$DS/generate-kg" "{\"project_id\":\"$PROJECT\"}"
wait_job kg_generation "$seen"

PGUSER_NAME="$(docker exec "$CONTAINER" printenv POSTGRES_USER)"
q() { docker exec "$CONTAINER" psql -U "$PGUSER_NAME" -d ennam_kg -At -c "$1"; }
tables="$(q "SELECT count(*) FROM source_tables st JOIN source_schemas ss ON ss.id = st.source_schema_id WHERE ss.data_source_id = '$DS'")"
nodes="$(q "SELECT count(*) || '/' || count(DISTINCT title) FROM latest_knowledge_nodes WHERE project_id = '$PROJECT' AND node_type = 'architecture' AND title LIKE 'public.%'")"
echo "source_tables=$tables architecture_nodes(total/distinct)=$nodes"
if [ "$tables" != "$EXPECTED_TABLES" ] || [ "$nodes" != "$EXPECTED_TABLES/$EXPECTED_TABLES" ]; then
  echo "expected $EXPECTED_TABLES source tables and $EXPECTED_TABLES/$EXPECTED_TABLES architecture nodes" >&2
  exit 1
fi
