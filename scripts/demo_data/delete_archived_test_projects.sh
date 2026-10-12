#!/usr/bin/env bash
# HARD-deletes archived DAAB test-leftover projects (and the rows that reference them) from the dev database.
# NOT reversible. Eligible = status 'archived' AND name matches a test pattern AND no members AND not in KEEP.
# Same deletion order as ennam.kg.go/internal/testutil/projects.go (cleanupSteps), set-based and in batches.
# Default is a DRY RUN (counts only). To delete: APPLY=1 CONFIRM_DELETE=yes bash scripts/demo_data/delete_archived_test_projects.sh
# A CSV of the deleted projects rows is saved to .superpowers/backups/ first.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/.superpowers/backups"
U=$(docker exec daab-postgres printenv POSTGRES_USER)
BATCH="${BATCH:-50}"
psqlq() { docker exec -i daab-postgres psql -U "$U" -d ennam_kg -X -v ON_ERROR_STOP=1 "$@"; }

KEEP="'592c7ff7-9f6f-4cc5-9094-d9b3b685277e','428a3084-43da-4edb-8656-4005a3b19825','b9a4d353-2bd9-458f-a78a-eb3b54998706','fd474397-491b-4cb1-9f5d-cc451eafbf46','93878d9b-e602-42ae-bd7d-42f6fd7c3e27','f881e3af-6add-454b-88bc-e81b9799134b','1fce9d24-459b-4bba-975d-142abe5918a1','0a30dfbf-10b9-4410-b0d2-07c0e1d36682','4ad7a5fa-a036-4f6a-8229-39a20af23e38','02d1f55d-ab02-4850-9a23-2c0bb9c32875','8078b024-3bef-447c-a15e-51e221a8d967'"
PATTERN='^(imp010-dr|live-unsynced|live-bind|intel_parity|mapdraft|chunk-content|intel_exec_ro_probe|exec-limit|exec-stmt-timeout|kgtest)[-_]'
WHERE="status = 'archived' AND id NOT IN ($KEEP) AND name ~ '$PATTERN' AND NOT EXISTS (SELECT 1 FROM project_members m WHERE m.project_id = projects.id)"

total=$(psqlq -At -c "select count(*) from projects where $WHERE")
echo "eligible archived test projects: $total"
echo "kept: $(psqlq -At -c "select count(*) from projects where id in ($KEEP)") human-named projects; other archived not eligible:"
psqlq -At -F ' | ' -c "select name from projects where status='archived' and not ($WHERE) order by created_at"
echo "rows that would go with them:"
psqlq -At -F ' | ' -c "
with p as (select id from projects where $WHERE)
select 'data_sources', count(*) from data_sources where project_id in (select id from p)
union all select 'knowledge_nodes', count(*) from knowledge_nodes where project_id in (select id from p)
union all select 'knowledge_edges', count(*) from knowledge_edges where project_id in (select id from p)
union all select 'ai_queries', count(*) from ai_queries where project_id in (select id from p)
union all select 'sessions', count(*) from sessions where project_id in (select id from p)
union all select 'audit_trail', count(*) from audit_trail where project_id in (select id from p)
union all select 'project_members (should be 0)', count(*) from project_members where project_id in (select id from p)"
if [ "${APPLY:-0}" != "1" ] || [ "${CONFIRM_DELETE:-}" != "yes" ]; then
  echo "DRY RUN only. To delete for real: APPLY=1 CONFIRM_DELETE=yes bash $0"; exit 0
fi

mkdir -p "$OUT"
stamp="$(date +%Y%m%d-%H%M)"
psqlq -c "\\copy (select * from projects where $WHERE order by created_at) to stdout csv header" > "$OUT/deleted-test-projects-$stamp.csv"
echo "saved project rows to $OUT/deleted-test-projects-$stamp.csv"

STEPS=$(cat <<'SQL'
UPDATE data_sources SET last_sync_job_id = NULL WHERE project_id = ANY(:'ids'::uuid[]);
DELETE FROM benchmark_results WHERE run_id IN (SELECT id FROM benchmark_runs WHERE project_id = ANY(:'ids'::uuid[]) OR data_source_id IN (SELECT id FROM data_sources WHERE project_id = ANY(:'ids'::uuid[]))) OR question_id IN (SELECT id FROM benchmark_questions WHERE data_source_id IN (SELECT id FROM data_sources WHERE project_id = ANY(:'ids'::uuid[])));
DELETE FROM benchmark_runs WHERE project_id = ANY(:'ids'::uuid[]) OR data_source_id IN (SELECT id FROM data_sources WHERE project_id = ANY(:'ids'::uuid[]));
DELETE FROM benchmark_questions WHERE data_source_id IN (SELECT id FROM data_sources WHERE project_id = ANY(:'ids'::uuid[]));
DELETE FROM query_clarifications WHERE query_id IN (SELECT id FROM ai_queries WHERE project_id = ANY(:'ids'::uuid[]) OR data_source_id IN (SELECT id FROM data_sources WHERE project_id = ANY(:'ids'::uuid[])));
DELETE FROM query_queue WHERE ai_query_id IN (SELECT id FROM ai_queries WHERE project_id = ANY(:'ids'::uuid[]) OR data_source_id IN (SELECT id FROM data_sources WHERE project_id = ANY(:'ids'::uuid[])));
DELETE FROM dead_letter_queue WHERE ai_query_id IN (SELECT id FROM ai_queries WHERE project_id = ANY(:'ids'::uuid[]) OR data_source_id IN (SELECT id FROM data_sources WHERE project_id = ANY(:'ids'::uuid[])));
DELETE FROM ai_queries WHERE project_id = ANY(:'ids'::uuid[]) OR data_source_id IN (SELECT id FROM data_sources WHERE project_id = ANY(:'ids'::uuid[]));
DELETE FROM project_mapping WHERE project_id = ANY(:'ids'::uuid[]);
DELETE FROM sync_jobs WHERE data_source_id IN (SELECT id FROM data_sources WHERE project_id = ANY(:'ids'::uuid[]));
DELETE FROM kg_generation_jobs WHERE data_source_id IN (SELECT id FROM data_sources WHERE project_id = ANY(:'ids'::uuid[]));
DELETE FROM source_schemas WHERE data_source_id IN (SELECT id FROM data_sources WHERE project_id = ANY(:'ids'::uuid[]));
DELETE FROM knowledge_edges WHERE project_id = ANY(:'ids'::uuid[]) OR source_id IN (SELECT id FROM knowledge_nodes WHERE project_id = ANY(:'ids'::uuid[])) OR target_id IN (SELECT id FROM knowledge_nodes WHERE project_id = ANY(:'ids'::uuid[]));
DELETE FROM knowledge_node_versions WHERE node_id IN (SELECT id FROM knowledge_nodes WHERE project_id = ANY(:'ids'::uuid[]));
DELETE FROM canonical_document WHERE project_id = ANY(:'ids'::uuid[]) OR knowledge_node_id IN (SELECT id FROM knowledge_nodes WHERE project_id = ANY(:'ids'::uuid[]));
DELETE FROM draft_nodes WHERE project_id = ANY(:'ids'::uuid[]) OR knowledge_node_id IN (SELECT id FROM knowledge_nodes WHERE project_id = ANY(:'ids'::uuid[]));
DELETE FROM knowledge_nodes WHERE project_id = ANY(:'ids'::uuid[]);
DELETE FROM sessions WHERE project_id = ANY(:'ids'::uuid[]);
DELETE FROM audit_trail WHERE project_id = ANY(:'ids'::uuid[]);
UPDATE api_keys SET default_project_id = NULL WHERE default_project_id = ANY(:'ids'::uuid[]);
DELETE FROM data_sources WHERE project_id = ANY(:'ids'::uuid[]);
DELETE FROM projects WHERE id = ANY(:'ids'::uuid[]) AND status = 'archived';
SQL
)

ALL=()
while IFS= read -r line; do [ -n "$line" ] && ALL+=("$line"); done < <(psqlq -At -c "select id from projects where $WHERE order by created_at")
done_n=0
for ((i=0; i<${#ALL[@]}; i+=BATCH)); do
  chunk=("${ALL[@]:i:BATCH}")
  ids="{$(IFS=,; echo "${chunk[*]}")}"
  { echo "BEGIN;"; echo "$STEPS"; echo "COMMIT;"; } | docker exec -i daab-postgres psql -U "$U" -d ennam_kg -X -q -v ON_ERROR_STOP=1 -v "ids=$ids" >/dev/null
  done_n=$((done_n + ${#chunk[@]}))
  echo "deleted $done_n / ${#ALL[@]}"
done
echo "remaining projects by status:"
psqlq -At -F ' | ' -c "select status, count(*) from projects group by 1 order by 1"
