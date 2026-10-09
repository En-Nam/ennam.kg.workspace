#!/usr/bin/env bash
# Make the pharmacy demo "young" again before a demo day: shift the ORIGINAL package (demo_mockdata/) by the
# largest multiple of 7 days that ends it on or before <as-of>, rebuild the store targets for that window, and
# print the cutover commands (runbook docs/superpowers/runbooks/2026-10-08-demo-date-shift.md).
#   scripts/demo_data/refresh_demo.sh <as-of YYYY-MM-DD> [<verified pg_dump -Fc backup of pharmacy_demo>]
# Non-destructive by default: it only writes demo_mockdata_shifted_<N>/ (untracked). It reloads the LIVE
# pharmacy_demo ONLY when CONFIRM_LIVE_RELOAD=yes AND a backup path are given (load_pharmacy_demo.sh re-checks both).
# <as-of> must not be after "today" in America/Chicago (kg-packs set-as-of refuses future dates); LAAM Home calls
# data stale when the analysis runs more than 7 days after the as-of, so pick the demo day or the day before.
# Env: REFRESH_REPLACE=yes to delete an existing demo_mockdata_shifted_<N>/ first.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
AS_OF="${1:-}"
BACKUP="${2:-}"
PROJECT="4ad7a5fa-a036-4f6a-8229-39a20af23e38"

if ! [[ "$AS_OF" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "usage: $0 <as-of YYYY-MM-DD> [<backup.dump>]" >&2
  exit 1
fi
CHICAGO_TODAY="$(TZ=America/Chicago date +%F)"
if [[ "$AS_OF" > "$CHICAGO_TODAY" ]]; then
  echo "as-of $AS_OF is after today in America/Chicago ($CHICAGO_TODAY): kg-packs set-as-of would refuse it" >&2
  exit 1
fi

cd "$HERE"
N="$(uv run python shift_dates.py --input "$ROOT/demo_mockdata" --days-for "$AS_OF")"
OUT="$ROOT/demo_mockdata_shifted_$N"
if [ -e "$OUT" ]; then
  if [ "${REFRESH_REPLACE:-}" = "yes" ] && [ -f "$OUT/SHIFT_MANIFEST.json" ]; then
    rm -rf "$OUT"
  else
    echo "$OUT exists — set REFRESH_REPLACE=yes to rebuild it" >&2
    exit 1
  fi
fi
uv run python shift_dates.py --input "$ROOT/demo_mockdata" --output "$OUT" --days "$N" > /dev/null
uv run python retarget_demo.py --data "$OUT"
END="$(uv run python -c "import shift_dates as S, pathlib; print(S.data_end(pathlib.Path('$OUT')))")"
# run-metrics must start at the ORIGINAL first day: the metric store deletes then rewrites the window, and every
# earlier refresh lies inside [original start, new end], so this always clears stale rows (empty ranges are harmless).
FROM_OLD="$(uv run python -c "import csv; print(min(r['transaction_datetime'][:10] for r in csv.DictReader(open('$ROOT/demo_mockdata/transactions.csv'))))")"
TO_EXCL="$(uv run python -c "from datetime import date, timedelta; print(date.fromisoformat('$END') + timedelta(days=1))")"

echo
echo "shift: +$N days -> data ends $END (wanted as-of $AS_OF); package: $OUT"
if [ "${CONFIRM_LIVE_RELOAD:-}" = "yes" ] && [ -n "$BACKUP" ]; then
  cd "$ROOT"
  DEMO_DATA_DIR="$OUT" DAAB_PG_CONTAINER=daab-postgres CONFIRM_LIVE_RELOAD=yes \
    scripts/demo_data/load_pharmacy_demo.sh "$BACKUP"
  U="$(docker exec daab-postgres printenv POSTGRES_USER)"
  docker exec -i daab-postgres psql -U "$U" -d pharmacy_demo -X -v shift_days="$N" -f - < scripts/demo_data/verify_plants.sql
  echo "pharmacy_demo reloaded. Continue with the steps below from 'resync'."
else
  echo "Nothing live was touched. Cutover commands (run from $ROOT, in this order):"
fi
cat <<EOF
  DEMO_DATA_DIR=$OUT DAAB_PG_CONTAINER=daab-postgres CONFIRM_LIVE_RELOAD=yes scripts/demo_data/load_pharmacy_demo.sh <backup.dump>
  DAAB_API_KEY=<key> scripts/demo_data/resync_daab_schema.sh
  docker exec -w /app daab-server go run ./cmd/kg-packs set-as-of --project $PROJECT --date $END
  curl -fsS -X POST -H "Authorization: Bearer \$DAAB_API_KEY" -F ingest_mode=tabular -F dataset_name=store_targets \\
       -F write_mode=replace -F file=@$OUT/targets.xlsx http://localhost:8082/api/v1/projects/$PROJECT/ingest/upload
  docker exec -w /app daab-server go run ./cmd/kg-packs run-metrics --project $PROJECT --from $FROM_OLD --to $TO_EXCL
  LAAM: business_project.asOfOverride='$END' for bp-pharmacy-chain-demo, then "Chạy ngay"; then
  node --env-file=LAAM/.env scripts/check-expected-findings.ts   # expect PASS 9/9
EOF
