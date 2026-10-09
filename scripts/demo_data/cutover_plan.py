"""Pure parts of the demo cutover (dates, Chicago time guard, command order) used by cutover.sh and refresh_demo.sh.

    uv run python cutover_plan.py --data ../../demo_mockdata_shifted_70 --shell   # AS_OF=… METRICS_FROM=… METRICS_TO=…
    uv run python cutover_plan.py --data … --check-time       # exit 2 while too early in Chicago
    uv run python cutover_plan.py --data … --print-commands   # the cutover, in order [--backup <dump>]

Order (learned in the 2026-10-09 cutover): load -> resync -> upload targets -> [Chicago day of the as-of has begun]
set-as-of -> run-metrics (CLI) -> upload targets AGAIN -> wait for the target metrics -> LAAM as-of + analysis ->
check the latest run only. The kg-packs CLI has no resolver for mode=file ("no source resolver for mode \"file\""),
so retail.target_net_sales / retail.target_gross_margin_pct are only recomputed by the in-server run that a targets
upload triggers; that run must happen AFTER set-as-of, otherwise the targets stay on the old month.
"""
import argparse
import csv
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple
from zoneinfo import ZoneInfo

import shift_dates as S

PROJECT = "4ad7a5fa-a036-4f6a-8229-39a20af23e38"
BUSINESS_PROJECT = "bp-pharmacy-chain-demo"
PROJECT_TZ = ZoneInfo("America/Chicago")   # DAAB resolves the pharmacy project's timezone to this


class Plan(NamedTuple):
    as_of: date          # last data day of the shifted package (inclusive)
    metrics_from: date   # FIRST day of the ORIGINAL package: run-metrics deletes+rewrites, so this clears old rows
    metrics_to: date     # as_of + 1 (exclusive)


def data_start(directory: Path) -> date:
    with (directory / "transactions.csv").open(newline="", encoding="utf-8") as fh:
        return min(date.fromisoformat(r["transaction_datetime"][:10]) for r in csv.DictReader(fh))


def make_plan(shifted_dir: Path, original_dir: Path) -> Plan:
    as_of = S.data_end(shifted_dir)
    return Plan(as_of, data_start(original_dir), as_of + timedelta(days=1))


def too_early(as_of: date, now_utc: datetime) -> bool:
    """kg-packs set-as-of refuses a date after 'today' in the project timezone."""
    return now_utc.astimezone(PROJECT_TZ).date() < as_of


def cutover_commands(plan: Plan, shifted_dir: str, backup: str) -> list[tuple[str, str]]:
    upload = ('curl -fsS -X POST -H "Authorization: Bearer $DAAB_API_KEY" -F ingest_mode=tabular '
              f'-F dataset_name=store_targets -F write_mode=replace -F file=@{shifted_dir}/targets.xlsx '
              f'"$DAAB_API_URL/api/v1/projects/{PROJECT}/ingest/upload"')
    kg = "docker exec -w /app daab-server go run ./cmd/kg-packs"
    return [
        ("load", f"DEMO_DATA_DIR={shifted_dir} DAAB_PG_CONTAINER=daab-postgres CONFIRM_LIVE_RELOAD=yes "
                 f"scripts/demo_data/load_pharmacy_demo.sh {backup}"),
        ("resync", "scripts/demo_data/resync_daab_schema.sh"),
        ("upload_targets", upload),
        ("set_as_of", f"# not before {plan.as_of} 00:00 America/Chicago\n{kg} set-as-of --project {PROJECT} "
                      f"--date {plan.as_of}"),
        ("run_metrics", f"{kg} run-metrics --project {PROJECT} --from {plan.metrics_from} --to {plan.metrics_to}"
                        "   # file-mode metrics (retail.target_*) fail here: expected"),
        ("reupload_targets", f"{upload}   # the server-side run recomputes retail.target_* at the new as-of"),
        ("wait_targets_current", "poll ennam_kg.data_status until no '%target%' subject is non-current and "
                                 f"metric:*target* period_to >= {plan.as_of.replace(day=1)}"),
        ("laam_as_of", f"business_project.asOfOverride='{plan.as_of}' for {BUSINESS_PROJECT} "
                       "(docker exec laam-v2-app node, app DATABASE_URL)"),
        ("laam_run", f"analysis_job.nextRunAt = now() - 1 minute for {BUSINESS_PROJECT}; wait for a new succeeded run"),
        ("check_latest_run", "export finding rows with lastRunId = latest run -> "
                             "node scripts/check-expected-findings.ts --findings-json <file>   # expect PASS 9/9"),
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, required=True, help="shifted package")
    ap.add_argument("--original", type=Path, default=S.DEFAULT_INPUT)
    ap.add_argument("--backup", default="<verified pg_dump -Fc backup of pharmacy_demo>")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--shell", action="store_true")
    mode.add_argument("--check-time", action="store_true")
    mode.add_argument("--print-commands", action="store_true")
    args = ap.parse_args(argv)
    plan = make_plan(args.data, args.original)
    if args.shell:
        print(f"AS_OF={plan.as_of} METRICS_FROM={plan.metrics_from} METRICS_TO={plan.metrics_to}")
    elif args.check_time:
        now = datetime.now(timezone.utc)
        if too_early(plan.as_of, now):
            print(f"too early: it is {now.astimezone(PROJECT_TZ):%Y-%m-%d %H:%M} in America/Chicago; "
                  f"set-as-of {plan.as_of} is refused until {plan.as_of} 00:00 there", file=sys.stderr)
            return 2
    else:
        for i, (step, cmd) in enumerate(cutover_commands(plan, str(args.data), args.backup), start=1):
            print(f"{i:2}. [{step}]\n    " + cmd.replace("\n", "\n    "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
