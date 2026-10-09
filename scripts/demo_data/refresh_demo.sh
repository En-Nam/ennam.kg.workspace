#!/usr/bin/env bash
# Make the pharmacy demo "young" again before a demo day: shift the ORIGINAL package (demo_mockdata/) by the
# largest multiple of 7 days that ends it on or before <as-of>, rebuild the store targets for that window, and
# print the cutover commands (runbook docs/superpowers/runbooks/2026-10-08-demo-date-shift.md).
#   scripts/demo_data/refresh_demo.sh <as-of YYYY-MM-DD> [<verified pg_dump -Fc backup of pharmacy_demo>]
# Non-destructive by default: it only writes demo_mockdata_shifted_<N>/ (untracked) and prints the cutover. With
# CONFIRM_LIVE_RELOAD=yes AND a backup path it runs cutover.sh part1 (reload pharmacy_demo, resync, upload targets;
# needs DAAB_API_KEY). Parts 2-3 (set-as-of, run-metrics, targets re-upload, LAAM) are always run by hand.
# <as-of> must not be after "today" in America/Chicago (kg-packs set-as-of refuses future dates); LAAM Home calls
# data stale when the analysis runs more than 7 days after the as-of, so pick the demo day or the day before.
# Env: REFRESH_REPLACE=yes to delete an existing demo_mockdata_shifted_<N>/ first.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
WANTED="${1:-}"
BACKUP="${2:-}"
PROJECT="4ad7a5fa-a036-4f6a-8229-39a20af23e38"

if ! [[ "$WANTED" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "usage: $0 <as-of YYYY-MM-DD> [<backup.dump>]" >&2
  exit 1
fi
CHICAGO_TODAY="$(TZ=America/Chicago date +%F)"
if [[ "$WANTED" > "$CHICAGO_TODAY" ]]; then
  echo "as-of $WANTED is after today in America/Chicago ($CHICAGO_TODAY): kg-packs set-as-of would refuse it" >&2
  exit 1
fi

cd "$HERE"
N="$(uv run python shift_dates.py --input "$ROOT/demo_mockdata" --days-for "$WANTED")"
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
eval "$(uv run python cutover_plan.py --data "$OUT" --original "$ROOT/demo_mockdata" --shell)"   # AS_OF METRICS_FROM METRICS_TO

echo
echo "shift: +$N days -> data ends $AS_OF (wanted as-of $WANTED); package: $OUT"
if [ "${CONFIRM_LIVE_RELOAD:-}" = "yes" ] && [ -n "$BACKUP" ]; then
  # Part 1 of the cutover: reload + plant/date checks + resync + first targets upload (needs DAAB_API_KEY).
  "$HERE/cutover.sh" part1 "$OUT" "$BACKUP"
  echo "Part 1 done. Next: scripts/demo_data/cutover.sh part2 $OUT (from $AS_OF 00:00 America/Chicago), then part3."
else
  echo "Nothing live was touched. Cutover = scripts/demo_data/cutover.sh part1|part2|part3 $OUT; the steps, in order:"
  uv run python cutover_plan.py --data "$OUT" --original "$ROOT/demo_mockdata" --print-commands \
    --backup "${BACKUP:-<verified pg_dump -Fc backup of pharmacy_demo>}"
fi
