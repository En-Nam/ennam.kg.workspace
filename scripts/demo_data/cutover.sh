#!/usr/bin/env bash
# Pharmacy demo cutover to a date-shifted package (built by refresh_demo.sh / shift_dates.py + retarget_demo.py).
# Generalised from the scripts that ran the 2026-10-09 cutover. Runbook: docs/superpowers/runbooks/2026-10-08-demo-date-shift.md
#
#   scripts/demo_data/cutover.sh part1 <shifted-dir> <pg_dump -Fc backup of pharmacy_demo>   # any time
#   scripts/demo_data/cutover.sh part2 <shifted-dir>   # once the as-of day has begun in America/Chicago
#   scripts/demo_data/cutover.sh part3 <shifted-dir>   # LAAM side
#
# part1: reload pharmacy_demo (needs CONFIRM_LIVE_RELOAD=yes + backup), verify plants and dates, resync DAAB, upload targets.
# part2: set-as-of, run-metrics (CLI), upload targets AGAIN and wait until the target metrics are current.
#        The kg-packs CLI has no resolver for mode=file, so only the server-side run that an upload triggers
#        recomputes retail.target_* at the new as-of. Skipping the second upload leaves 3 "late data" warnings on
#        LAAM Home and FND-008 (RET-SALES-001, PH-004) missing.
# part3: LAAM asOfOverride + one analysis run, then check-expected-findings on the findings of THAT run only.
# Env: DAAB_API_KEY (parts 1-2, developer role on the project; never printed), DAAB_API_URL (default: localhost +
#      KG_SERVER_PORT from the workspace .env, else 8082). LAAM is reached with `docker exec laam-v2-app node`
#      using the app's own DATABASE_URL (never printed). Nothing touches port 5432.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PART="${1:-}"
DATA_ARG="${2:-}"
BACKUP="${3:-}"
PROJECT="4ad7a5fa-a036-4f6a-8229-39a20af23e38"
BP="bp-pharmacy-chain-demo"
WAIT_STEPS=30            # x 10 s

usage() { echo "usage: $0 part1 <shifted-dir> <backup.dump> | part2 <shifted-dir> | part3 <shifted-dir>" >&2; exit 1; }
case "$PART" in part1|part2|part3) ;; *) usage ;; esac
[ -n "$DATA_ARG" ] || usage
if [ "$PART" = "part1" ] && { [ -z "$BACKUP" ] || [ "${CONFIRM_LIVE_RELOAD:-}" != "yes" ]; }; then
  echo "part1 reloads the LIVE pharmacy_demo: pass a verified backup and set CONFIRM_LIVE_RELOAD=yes" >&2
  exit 1
fi
DATA="$(cd "$ROOT" && cd "$DATA_ARG" && pwd)"
[ -f "$DATA/SHIFT_MANIFEST.json" ] && [ -s "$DATA/targets.xlsx" ] || { echo "$DATA is not a shifted+retargeted package" >&2; exit 1; }

py() { (cd "$HERE" && uv run python "$@"); }
eval "$(py cutover_plan.py --data "$DATA" --original "$ROOT/demo_mockdata" --shell)"   # AS_OF METRICS_FROM METRICS_TO
SHIFT_DAYS="$(py -c "import json,sys; print(json.load(open(sys.argv[1]))['days'])" "$DATA/SHIFT_MANIFEST.json")"
U="$(docker exec daab-postgres printenv POSTGRES_USER)"
kg_sql() { docker exec daab-postgres psql -U "$U" -d ennam_kg -At -c "$1"; }

api_url() {
  if [ -n "${DAAB_API_URL:-}" ]; then echo "$DAAB_API_URL"; return; fi
  local port="${KG_SERVER_PORT:-}"
  if [ -z "$port" ] && [ -f "$ROOT/.env" ]; then port="$(grep -E '^KG_SERVER_PORT=' "$ROOT/.env" | tail -1 | cut -d= -f2)"; fi
  echo "http://localhost:${port:-8082}"
}

upload_targets() {
  : "${DAAB_API_KEY:?export DAAB_API_KEY (developer role on the pharmacy project)}"
  curl -fsS -X POST -H "Authorization: Bearer $DAAB_API_KEY" -F ingest_mode=tabular -F dataset_name=store_targets \
    -F write_mode=replace -F "file=@$DATA/targets.xlsx" "$(api_url)/api/v1/projects/$PROJECT/ingest/upload" > /dev/null
  echo "store_targets row_count: $(kg_sql "select row_count from file_dataset where project_id='$PROJECT' and name='store_targets'")"
}

laam_node() {  # $1 = JS body run inside laam-v2-app with a connected pg Client `c`; env passed with -e
  docker exec -i -e AS_OF="$AS_OF" -e BP="$BP" -e RUN_ID="${RUN_ID:-}" -w /app laam-v2-app node --input-type=commonjs - <<JS
const { Client } = require("pg");
(async () => {
  const c = new Client({ connectionString: process.env.DATABASE_URL });
  await c.connect();
  try { $1 } finally { await c.end(); }
})().catch((e) => { console.error("ERR " + e.message); process.exit(1); });
JS
}

part1() {
  echo "== load $DATA into pharmacy_demo (+$SHIFT_DAYS days)"
  (cd "$ROOT" && DEMO_DATA_DIR="$DATA" DAAB_PG_CONTAINER=daab-postgres CONFIRM_LIVE_RELOAD=yes scripts/demo_data/load_pharmacy_demo.sh "$BACKUP")
  echo "== planted patterns (must equal the original except the window)"
  docker exec -i daab-postgres psql -U "$U" -d pharmacy_demo -X -v shift_days="$SHIFT_DAYS" -f - < "$HERE/verify_plants.sql"
  local last
  last="$(docker exec daab-postgres psql -U "$U" -d pharmacy_demo -At -c "select max(transaction_datetime)::date from transactions")"
  echo "max transaction date: $last (expected $AS_OF)"
  [ "$last" = "$AS_OF" ] || { echo "unexpected data end" >&2; exit 1; }
  echo "== resync DAAB schema"
  "$HERE/resync_daab_schema.sh"
  echo "== upload store_targets (replace)"
  upload_targets
  echo "PART 1 DONE. Part 2 from $AS_OF 00:00 America/Chicago."
}

part2() {
  py cutover_plan.py --data "$DATA" --original "$ROOT/demo_mockdata" --check-time || exit 2
  echo "== set-as-of $AS_OF"
  docker exec -w /app daab-server go run ./cmd/kg-packs set-as-of --project "$PROJECT" --date "$AS_OF"
  echo "== run-metrics $METRICS_FROM .. $METRICS_TO (file-mode target metrics are expected to fail here)"
  docker exec -w /app daab-server go run ./cmd/kg-packs run-metrics --project "$PROJECT" --from "$METRICS_FROM" --to "$METRICS_TO" \
    > /dev/null || echo "run-metrics reported problems (expected for retail.target_*); continuing with the re-upload"
  echo "== upload store_targets AGAIN: the server-side run recomputes retail.target_* at as-of $AS_OF"
  upload_targets
  local month="${AS_OF:0:8}01" bad late
  for _ in $(seq 1 "$WAIT_STEPS"); do
    sleep 10
    bad="$(kg_sql "select count(*) from data_status where project_id='$PROJECT' and subject like '%target%' and status <> 'current'")"
    late="$(kg_sql "select count(*) from data_status where project_id='$PROJECT' and subject like 'metric:%target%' and (period_to is null or period_to < date '$month')")"
    echo "  target subjects not current: $bad | target metrics before $month: $late"
    if [ "$bad" = "0" ] && [ "$late" = "0" ]; then break; fi
  done
  kg_sql "select subject || ' ' || status || ' ' || coalesce(period_to::text,'-') from data_status where project_id='$PROJECT' and subject like '%target%' order by 1"
  echo "non-current data_status rows (expect 0): $(kg_sql "select count(*) from data_status where project_id='$PROJECT' and status <> 'current'")"
  [ "$bad" = "0" ] && [ "$late" = "0" ] || { echo "target metrics are not current — stop and investigate" >&2; exit 1; }
  echo "PART 2 DONE."
}

part3() {
  echo "== LAAM: asOfOverride=$AS_OF for $BP and trigger the analysis"
  local before after
  before="$(laam_node 'const r = await c.query(`select max("finishedAt") m from analysis_run where "businessProjectId"=$1 and status=$2`, [process.env.BP, "succeeded"]); console.log(r.rows[0].m ? new Date(r.rows[0].m).toISOString() : "");')"
  laam_node 'const a = await c.query(`update business_project set "asOfOverride"=$1, "updatedAt"=now() where id=$2`, [process.env.AS_OF, process.env.BP]);
    const j = await c.query(`update analysis_job set "nextRunAt"=now() - interval '\''1 minute'\'', "updatedAt"=now() where "businessProjectId"=$1`, [process.env.BP]);
    console.log("business_project:", a.rowCount, "analysis_job:", j.rowCount);'
  for _ in $(seq 1 "$WAIT_STEPS"); do
    sleep 10
    after="$(laam_node 'const r = await c.query(`select max("finishedAt") m from analysis_run where "businessProjectId"=$1 and status=$2`, [process.env.BP, "succeeded"]); console.log(r.rows[0].m ? new Date(r.rows[0].m).toISOString() : "");')"
    echo "  latest succeeded run: ${after:-none}"
    [ "$after" != "$before" ] && break
  done
  [ "$after" != "$before" ] || { echo "no new analysis run; check docker logs laam-v2-tick / laam-v2-app" >&2; exit 1; }
  RUN_ID="$(laam_node 'const r = await c.query(`select id from analysis_run where "businessProjectId"=$1 and status=$2 order by "finishedAt" desc limit 1`, [process.env.BP, "succeeded"]); console.log(r.rows[0].id);')"
  local out
  out="$(mktemp -t findings-latest-run.XXXXXX)"
  laam_node 'const r = await c.query(`select "ruleId", dims, severity from finding where "projectId"=$1 and "lastRunId"=$2`, [process.env.BP, process.env.RUN_ID]); console.log(JSON.stringify(r.rows));' > "$out"
  echo "== check-expected-findings on run $RUN_ID only"
  (cd "$ROOT" && node scripts/check-expected-findings.ts --findings-json "$out")
}

"$PART"
