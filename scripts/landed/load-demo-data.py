#!/usr/bin/env python3
"""Load the synthetic pharmacy demo T-logs into a DAAB project's landed store through the public API
(the normal ingest path: upload -> worker -> landed_record), then point the project's mapping at landed
and recalculate October 2026.

Usage (run from the workspace root, with ennam.kg.python's venv: `uv run --project ennam.kg.python python ...`):
  DAAB_URL=https://<daab-host> DAAB_API_KEY=<admin or owner key> PROJECT_ID=<project uuid> \
  DEMO_DATA_DIR=<dir with master/*.csv and poslog30/<store>/*.xml> \
  python scripts/landed/load-demo-data.py [--dry-run]

Idempotent: re-running re-uses the feed; identical files are reported as duplicates, not loaded twice.
The data is synthetic (no real customers or payment data). Use only on a demo project.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ennam.kg.python" / "scripts" / "landed_demo"))
from landed_driver import Driver  # noqa: E402

FEED_NAME, CROSSWALK, VENDOR = "PH POSLog", "poslog-6.0-rx", "pos-vendor-a"
MASTERS = ("location", "product", "employee")
AUTOFILL = ["location", "product", "employee", "sale", "sale_line", "tender", "refund", "void",
            "line_void", "price_override", "sale_adjustment", "register_event"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="only list what would be uploaded")
    ap.add_argument("--poslog-dir", default="poslog30", help="T-log folder under DEMO_DATA_DIR (default poslog30)")
    ap.add_argument("--from", dest="day_from", default="2026-10-01", help="first day to recalculate")
    ap.add_argument("--to", dest="day_to", default="2026-10-31", help="last day to recalculate")
    a = ap.parse_args()
    data = Path(os.environ["DEMO_DATA_DIR"])
    masters = [data / "master" / f"{m}.csv" for m in MASTERS]
    files = sorted((data / a.poslog_dir).glob("*/*.xml"))
    missing = [str(p) for p in masters if not p.is_file()]
    if missing or not files:
        print(f"missing data: masters={missing} poslog_files={len(files)}", file=sys.stderr)
        return 2
    print(f"project {os.environ['PROJECT_ID']}: {len(masters)} master files, {len(files)} T-log files")
    if a.dry_run:
        return 0
    d = Driver(os.environ["DAAB_URL"].rstrip("/"), os.environ["DAAB_API_KEY"], os.environ["PROJECT_ID"])
    # Turning the landed source on needs a server admin signed in as a person (consent); an API key cannot.
    st = d._call("GET", "/landed")
    st.raise_for_status()
    if not st.json().get("enabled"):
        print("T-log source is off for this project. A server admin must turn it on first: dashboard -> project ->"
              " 'POS data' tab -> turn on (consent note: synthetic demo data). Then re-run this script.", file=sys.stderr)
        return 3
    print("landed source: enabled")
    for m, p in zip(MASTERS, masters):
        r = d.upload_master(m, p)
        print("master", m, r.get("status"), "duplicate" if r.get("duplicate") else "")
    feed = next((f for f in d.feeds() if f.get("name") == FEED_NAME), None) or d.create_feed(FEED_NAME, CROSSWALK, VENDOR)
    res = d.upload_all(feed["id"], files)
    print("uploaded", len(res), "duplicates", sum(1 for r in res if r.get("duplicate")))
    print("upload failures", sum(1 for r in res if r.get("error")))
    print("autofill", d.autofill(AUTOFILL))
    print("recalculate", a.day_from, "..", a.day_to, d.recalculate(a.day_from, a.day_to, timeout=3600).get("state"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
