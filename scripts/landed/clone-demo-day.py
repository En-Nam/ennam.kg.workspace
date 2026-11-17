#!/usr/bin/env python3
"""Add a new business day to the synthetic POSLog demo set by cloning the same weekday one week earlier.

    python3 scripts/landed/clone-demo-day.py --src-dir <poslog dir> --day 2026-11-16 --out <dir>

Why: the demo T-logs end on a fixed day, so every day after it DAAB reports every data set as "late" and the
LAAM briefing fills with warnings. Cloning day D-7 per store keeps each store's weekday pattern (and the planted
anomalies, which repeat in the week before) without a generator.

What changes in the clone: every date equal to D-7 becomes D (BusinessDayDate, Begin/EndDateTime), and every
transaction id DEFINED in the file (a Transaction's own SequenceNumber, e.g. TXN-1016257) gets a day prefix
(TXN-11161016257), including references to it inside the same file. References to transactions of other days
(a refund's OriginalTransaction from October) are left as they are, so they still point at a real sale.
Line SequenceNumbers (001, 002, ...) are not ids and are not touched. The data is synthetic; demo use only.
"""
import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

TXN_ID = re.compile(r"^([A-Z]{2,5})-(\d[\w-]*)$")


def own_transaction_ids(xml: str) -> list[str]:
    """Ids of the transactions this file defines: the first SequenceNumber after each <Transaction> opening tag."""
    ids = []
    for chunk in re.split(r"<Transaction[\s>]", xml)[1:]:
        m = re.search(r"<SequenceNumber>([^<]+)</SequenceNumber>", chunk)
        if m and TXN_ID.match(m.group(1).strip()):
            ids.append(m.group(1).strip())
    return ids


def clone(xml: str, src: date, day: date) -> str:
    stamp = day.strftime("%m%d")
    out = xml
    for old in own_transaction_ids(xml):
        prefix, digits = TXN_ID.match(old).groups()
        out = re.sub(rf">{re.escape(old)}<", f">{prefix}-{stamp}{digits}<", out)
    return out.replace(src.isoformat(), day.isoformat())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-dir", type=Path, required=True, help="POSLog folder with <store>/<YYYY-MM-DD>.xml")
    ap.add_argument("--day", type=date.fromisoformat, required=True, help="new business day to create")
    ap.add_argument("--out", type=Path, required=True, help="output folder (<store>/<day>.xml is written)")
    a = ap.parse_args()
    src = a.day - timedelta(days=7)
    stores = sorted(p for p in a.src_dir.iterdir() if p.is_dir())
    if not stores:
        print(f"no store folders in {a.src_dir}", file=sys.stderr)
        return 2
    for store in stores:
        f = store / f"{src.isoformat()}.xml"
        if not f.is_file():
            print(f"{store.name}: no {f.name}, skipped", file=sys.stderr)
            continue
        target = a.out / store.name / f"{a.day.isoformat()}.xml"
        if target.exists():
            print(f"{store.name}: {target.name} already exists, kept")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        xml = f.read_text(encoding="utf-8")
        target.write_text(clone(xml, src, a.day), encoding="utf-8")
        print(f"{store.name}: {src} -> {a.day}, {len(own_transaction_ids(xml))} transactions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
