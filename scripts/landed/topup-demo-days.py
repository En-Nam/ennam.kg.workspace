#!/usr/bin/env python3
"""Top up the demo T-log feed of a DAAB project up to a given day (default: yesterday), in one command.

    DAAB_URL=https://<daab-host> DAAB_API_KEY=<admin key> PROJECT_ID=<project uuid> \
    uv run --project ennam.kg.python python scripts/landed/topup-demo-days.py [--to 2026-11-24] [--from ...] [--dry-run]

Why: the demo POSLog set ends on a fixed day and there is no scheduler on the demo project yet, so every day
after it DAAB reports the data as late. This script:
  1. copies the base POSLog folder (--src-dir) to a temp folder and, for every missing day up to --to, clones
     the same weekday one week earlier (clone-demo-day.py; a cloned day can itself be the source a week later);
  2. uploads the days --from..--to of every store to the "PH POSLog" feed;
  3. admin-replays batches that hit conflicts (a changed re-upload, see the landed re-upload note), then
     re-applies the landed mapping and recalculates --from..--to.

Cloning is deterministic, so a day that is already loaded uploads the same bytes and is reported as a
duplicate, not loaded twice. Re-running is safe. The data is synthetic; use only on a demo project.
"""
import argparse
import importlib.util
import os
import shutil
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SRC = ROOT / ".superpowers/sdd/2026-11-11-pos-data-model-tlog-landed/e2e-data/poslog-12m-risk"
FEED_NAME = "PH POSLog"
AUTOFILL = ["location", "product", "employee", "target", "sale", "sale_line", "tender", "refund", "void",
            "line_void", "price_override", "sale_adjustment", "register_event"]  # same as load-demo-data.py
CHUNK = 40  # a chunk's batches must stay inside the API's "latest 100 batches" list
TERMINAL = {"done", "failed"}
REPLAY_ROUNDS = 3

_spec = importlib.util.spec_from_file_location("clone_demo_day", Path(__file__).with_name("clone-demo-day.py"))
clone_demo_day = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(clone_demo_day)


def last_day(folder: Path) -> date:
    """Latest <YYYY-MM-DD>.xml day across all store folders."""
    days = [date.fromisoformat(f.stem) for f in folder.glob("*/*.xml")]
    if not days:
        raise SystemExit(f"no <store>/<YYYY-MM-DD>.xml files in {folder}")
    return max(days)


def extend(work: Path, to: date) -> list[date]:
    """Clone every missing day after the last one in `work` up to `to`, in order, inside `work`. Returns the new days."""
    added = []
    day = last_day(work) + timedelta(days=1)
    while day <= to:
        src = day - timedelta(days=7)
        for store in sorted(p for p in work.iterdir() if p.is_dir()):
            f = store / f"{src.isoformat()}.xml"
            target = store / f"{day.isoformat()}.xml"
            if f.is_file() and not target.exists():
                target.write_text(clone_demo_day.clone(f.read_text(encoding="utf-8"), src, day), encoding="utf-8")
        added.append(day)
        day += timedelta(days=1)
    return added


def files_between(work: Path, day_from: date, day_to: date) -> list[Path]:
    return sorted(f for f in work.glob("*/*.xml") if day_from <= date.fromisoformat(f.stem) <= day_to)


def counts(b: dict) -> dict:
    c = b.get("counts") or {}
    return c if isinstance(c, dict) else {}


def wait(d, feed: str, ids: set[str], label: str, timeout: float = 3600) -> dict[str, dict]:
    deadline = time.monotonic() + timeout
    while True:
        latest = {b["id"]: b for b in d.batches(feed)}
        missing = [i for i in ids if i not in latest]
        if missing:
            raise RuntimeError(f"{label}: {len(missing)} batches not in the latest-100 list")
        done = {i: latest[i] for i in ids if latest[i].get("status") in TERMINAL}
        if len(done) == len(ids):
            return done
        if time.monotonic() > deadline:
            raise TimeoutError(f"{label}: {len(done)}/{len(ids)} finished")
        time.sleep(10)


def upload(d, feed: str, files: list[Path]) -> dict[str, dict]:
    final: dict[str, dict] = {}
    dup = 0
    t0 = time.monotonic()
    for start in range(0, len(files), CHUNK):
        ids: set[str] = set()
        dups: set[str] = set()
        for f in files[start:start + CHUNK]:
            r = d.upload(feed, f)
            bid = (r.get("batch") or {}).get("id")
            if not bid:
                raise RuntimeError(f"upload {f.parent.name}/{f.name}: no batch id in response keys {sorted(r)}")
            if r.get("duplicate"):
                dup += 1
                dups.add(bid)
            ids.add(bid)
        recent = {b["id"] for b in d.batches(feed)}
        ids -= {i for i in dups if i not in recent}  # identical bytes loaded long ago: nothing to wait for
        res = wait(d, feed, ids, f"chunk {start}") if ids else {}
        for rnd in range(1, REPLAY_ROUNDS + 1):
            todo = [i for i, b in res.items() if b.get("status") == "done" and counts(b).get("conflicts", 0) > 0]
            if not todo:
                break
            for i in todo:
                r = d.replay(feed, i)
                if r.status_code not in (200, 202):
                    print(f"replay {i}: HTTP {r.status_code} {r.text[:200]}", flush=True)
            time.sleep(5)
            res.update(wait(d, feed, set(todo), f"chunk {start} replay {rnd}"))
        final.update(res)
        print(f"{min(start + CHUNK, len(files))}/{len(files)} files; batches {len(final)}; "
              f"duplicates {dup}; {int(time.monotonic() - t0)}s", flush=True)
    return final


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-dir", type=Path, default=DEFAULT_SRC, help="base POSLog folder <store>/<YYYY-MM-DD>.xml")
    ap.add_argument("--to", type=date.fromisoformat, default=date.today() - timedelta(days=1),
                    help="last day to load (default: yesterday)")
    ap.add_argument("--from", dest="day_from", type=date.fromisoformat,
                    help="first day to upload and recalculate (default: 6 days before --to)")
    ap.add_argument("--dry-run", action="store_true", help="build the files and list them, upload nothing")
    a = ap.parse_args()
    day_from = a.day_from or a.to - timedelta(days=6)
    if day_from > a.to:
        ap.error("--from is after --to")

    with tempfile.TemporaryDirectory(prefix="tlog-topup-") as tmp:
        work = Path(tmp) / "poslog"
        shutil.copytree(a.src_dir, work)
        added = extend(work, a.to)
        files = files_between(work, day_from, a.to)
        print(f"cloned {len(added)} days after {a.src_dir.name}; uploading {len(files)} files "
              f"for {day_from}..{a.to}", flush=True)
        if a.dry_run:
            for f in files:
                print(" ", f.parent.name, f.name)
            return 0
        if not files:
            print("nothing to upload")
            return 1

        sys.path.insert(0, str(ROOT / "ennam.kg.python" / "scripts" / "landed_demo"))
        from landed_driver import Driver

        d = Driver(os.environ["DAAB_URL"].rstrip("/"), os.environ["DAAB_API_KEY"], os.environ["PROJECT_ID"])
        feed = next((f["id"] for f in d.feeds() if f.get("name") == FEED_NAME), None)
        if not feed:
            print(f'no "{FEED_NAME}" feed in this project; load the demo first (load-demo-data.py)')
            return 2
        final = upload(d, feed, files)

    d.autofill(AUTOFILL)
    print("recalculate", day_from, a.to, d.recalculate(day_from.isoformat(), a.to.isoformat(), timeout=3600).get("state"))
    bad = [i for i, b in final.items() if counts(b).get("conflicts", 0) > 0 or b.get("status") == "failed"]
    print(f"done: {len(final)} batches, {len(bad)} with problems")
    for i in bad[:15]:
        b = final[i]
        print("check", i, b.get("status"), counts(b), (b.get("error") or "")[:200])
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
