#!/usr/bin/env bash
# Archives (does NOT delete) DAAB projects that are test leftovers, so they disappear from /projects but can be restored.
# A project is archived only if ALL are true:
#   - status = 'active'
#   - it is not in the KEEP list (by id)
#   - it has no members
#   - its name looks like a test artifact (known prefixes below)
# Default is a DRY RUN. Set APPLY=1 to archive. The archived ids are saved to .superpowers/backups/ so the change can
# be reverted with: update projects set status='active', archived_at=null, archived_by=null where id in (<ids>);
# DAAB has no hard delete for projects (eight tables reference projects without ON DELETE CASCADE).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/.superpowers/backups"
U=$(docker exec daab-postgres printenv POSTGRES_USER)
psqlq() { docker exec -i daab-postgres psql -U "$U" -d ennam_kg -X -v ON_ERROR_STOP=1 "$@"; }

# Human-named projects to keep: Cảng Định An M&A, C4K Staging, Sala Food, Dasin, Cảng Định An v3, Salonbookly,
# Salonbookly V2, Salonbookly v3, Pharmacy Chain, Halcom PM3, Upload S3 Test.
KEEP="'592c7ff7-9f6f-4cc5-9094-d9b3b685277e','428a3084-43da-4edb-8656-4005a3b19825','b9a4d353-2bd9-458f-a78a-eb3b54998706','fd474397-491b-4cb1-9f5d-cc451eafbf46','93878d9b-e602-42ae-bd7d-42f6fd7c3e27','f881e3af-6add-454b-88bc-e81b9799134b','1fce9d24-459b-4bba-975d-142abe5918a1','0a30dfbf-10b9-4410-b0d2-07c0e1d36682','4ad7a5fa-a036-4f6a-8229-39a20af23e38','02d1f55d-ab02-4850-9a23-2c0bb9c32875','8078b024-3bef-447c-a15e-51e221a8d967'"
PATTERN='^(imp010-dr|live-unsynced|live-bind|intel_parity|mapdraft|chunk-content|intel_exec_ro_probe|exec-limit|exec-stmt-timeout|kgtest)[-_]'
WHERE="status = 'active' AND id NOT IN ($KEEP) AND name ~ '$PATTERN' AND NOT EXISTS (SELECT 1 FROM project_members m WHERE m.project_id = projects.id)"

echo "== kept (human-named):"
psqlq -At -F ' | ' -c "select name, status from projects where id in ($KEEP) order by created_at"
echo "== candidates to archive:"
psqlq -At -F ' | ' -c "select regexp_replace(name, '[-_][0-9a-f-]{8,}\$', '') p, count(*) from projects where $WHERE group by 1 order by 2 desc"
total=$(psqlq -At -c "select count(*) from projects where $WHERE")
echo "total to archive: $total"
echo "== active projects neither kept nor matching a test pattern (should be 0):"
psqlq -At -F ' | ' -c "select id, name from projects where status='active' and id not in ($KEEP) and not (name ~ '$PATTERN') limit 20"
if [ "${APPLY:-0}" != "1" ]; then echo "DRY RUN only. Re-run with APPLY=1 to archive."; exit 0; fi

mkdir -p "$OUT"
ids="$OUT/archived-test-project-ids-$(date +%Y%m%d-%H%M).txt"
psqlq -At -c "select id from projects where $WHERE" > "$ids"
echo "saved $(wc -l < "$ids" | tr -d ' ') ids to $ids"
psqlq -At -c "with u as (update projects set status='archived', archived_at=now(), archived_by=null, updated_at=now() where $WHERE returning 1) select count(*) from u" | awk '{print "archived:", $1}'
