"""Shift every date/timestamp of the pharmacy_demo loader CSVs by N days (default 63 = 9 weeks).

    uv run python shift_dates.py [--input ../../demo_mockdata] [--output ../../demo_mockdata_shifted]
                                 [--days 63] [--dry-run]

Columns are shifted by their SCHEMA TYPE (date / timestamp in schema/base.sql + extension.sql), never by
guessing from content. Only the leading YYYY-MM-DD of a cell changes: time-of-day, empty cells (NULL) and
every non-date column stay byte-identical. A multiple of 7 keeps every weekday, so same-weekday baselines and
weekday seasonality survive. The output carries SHIFT_MANIFEST.json; an input that has one is refused
(no accidental double shift), as is writing in place, into demo_mockdata/, or into a non-empty directory.
"""
import argparse
import csv
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[1]
DEFAULT_INPUT = WORKSPACE / "demo_mockdata"
DEFAULT_OUTPUT = WORKSPACE / "demo_mockdata_shifted"
SCHEMA_FILES = (HERE / "schema" / "base.sql", HERE / "schema" / "extension.sql")
MANIFEST = "SHIFT_MANIFEST.json"

LOAD_ORDER = (  # same tables and order as load_pharmacy_demo.sh
    "stores", "vendors", "products", "employees", "customers", "transactions", "transaction_items", "payments",
    "receipts", "invoices", "refunds", "refund_items", "voids", "discount_overrides", "cash_drawers",
    "employee_shifts", "inventory_movements", "inventory_adjustments", "inventory_snapshots", "prescriptions",
    "insurance_claims", "audit_events", "product_costs", "purchase_orders", "purchase_order_lines",
)

# Non-date columns whose content looks date-like or encodes a date/weekday relation, and why they stay as-is.
TEXT_COLUMN_DECISIONS = {
    ("invoices", "invoice_number"): "year-prefixed sequence (2026-NNNNNN); kept — every shifted issued_datetime "
                                    "is still in 2026, and renumbering could collide with the UNIQUE constraint",
}
INVARIANT_COLUMNS = {
    ("refunds", "days_after_purchase"): "day delta between two shifted dates — invariant under a uniform shift",
    ("prescriptions", "turnaround_minutes"): "duration — invariant",
    ("vendors", "order_weekday"): "weekday number 0-6 — invariant because days % 7 == 0",
    ("vendors", "lead_time_days"): "duration — invariant",
}

DATE_TYPE = re.compile(r"^(date|timestamp)\b", re.IGNORECASE)
CREATE_RE = re.compile(r"CREATE TABLE (?:public\.)?(\w+) \((.*?)\n\);", re.DOTALL)
ADD_COL_RE = re.compile(r"ALTER TABLE (?:ONLY )?(?:public\.)?(\w+) ADD COLUMN (\w+) ([^;]+);", re.IGNORECASE)
CELL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2}(\.\d+)?)?$")
TEXT_DATE_RE = re.compile(
    r"(?<!\d)(19|20)\d\d-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])(?!\d)"   # ISO date
    r"|(?<!\d)20\d\d(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)"          # compact yyyymmdd
    r"|^(19|20)\d\d[-/]\d+$"                                              # year-prefixed sequence
    r"|\b(January|February|March|April|June|July|August|September|October|November|December)\b"
    r"|\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b")


class ShiftError(Exception):
    pass


def date_columns_from_schema(sql: str) -> dict[str, set[str]]:
    """table -> columns typed date/timestamp, from CREATE TABLE bodies and ALTER TABLE ... ADD COLUMN."""
    cols: dict[str, set[str]] = {}
    for table, body in CREATE_RE.findall(sql):
        cols.setdefault(table, set())
        for line in body.splitlines():
            parts = line.strip().rstrip(",").split(None, 1)
            if len(parts) == 2 and DATE_TYPE.match(parts[1]):
                cols[table].add(parts[0])
    for table, column, typ in ADD_COL_RE.findall(sql):
        cols.setdefault(table, set())
        if DATE_TYPE.match(typ.strip()):
            cols[table].add(column)
    return cols


def all_columns_from_schema(sql: str) -> dict[str, set[str]]:
    cols: dict[str, set[str]] = {}
    for table, body in CREATE_RE.findall(sql):
        cols[table] = {p.strip().split(None, 1)[0] for p in body.splitlines()
                       if p.strip() and not p.strip().upper().startswith(("CONSTRAINT", "PRIMARY", "--"))}
    for table, column, _ in ADD_COL_RE.findall(sql):
        cols.setdefault(table, set()).add(column)
    return cols


def shift_value(value: str, days: int) -> str:
    if value == "":
        return value
    if not CELL_RE.match(value):
        raise ValueError(f"not an ISO date/timestamp: {value!r}")
    return (date.fromisoformat(value[:10]) + timedelta(days=days)).isoformat() + value[10:]


def _tables_in(directory: Path, tables) -> list[str]:
    return list(tables) if tables is not None else sorted(p.stem for p in directory.glob("*.csv"))


def scan_text_dates(directory: Path, date_cols: dict[str, set[str]], tables=None) -> dict[tuple[str, str], list[str]]:
    """(table, column) -> up to 3 examples of date-like text found in columns NOT typed date/timestamp."""
    hits: dict[tuple[str, str], list[str]] = {}
    for table in _tables_in(directory, tables):
        with (directory / f"{table}.csv").open(newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            header = next(reader)
            idx = [i for i, c in enumerate(header) if c not in date_cols.get(table, set())]
            for row in reader:
                for i in idx:
                    if row[i] and TEXT_DATE_RE.search(row[i]):
                        ex = hits.setdefault((table, header[i]), [])
                        if len(ex) < 3:
                            ex.append(row[i])
    return hits


def _check_paths(src: Path, out: Path, allow_reshift: bool) -> None:
    src, out = src.resolve(), out.resolve()
    if src == out:
        raise ShiftError("input and output are the same directory — refusing to shift in place")
    if out == DEFAULT_INPUT.resolve() or DEFAULT_INPUT.resolve() in out.parents:
        raise ShiftError(f"refusing to write into demo_mockdata ({out})")
    if (src / MANIFEST).exists() and not allow_reshift:
        raise ShiftError(f"{src} is already shifted ({MANIFEST} present) — refusing a double shift")
    if out.exists() and any(out.iterdir()):
        raise ShiftError(f"output directory {out} is not empty — remove it first")


def _shift_table(src: Path, table: str, date_cols: set[str], known: set[str] | None, days: int,
                 writer_path: Path | None, stats: dict) -> None:
    with (src / f"{table}.csv").open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        if known is not None:
            unknown = [c for c in header if c not in known]
            if unknown:
                raise ShiftError(f"{table}.csv has columns not in the schema: {unknown}")
        idx = [i for i, c in enumerate(header) if c in date_cols]
        out_fh = writer_path.open("w", newline="", encoding="utf-8") if writer_path else None
        try:
            writer = csv.writer(out_fh, lineterminator="\n") if out_fh else None
            if writer:
                writer.writerow(header)
            col_stats = {header[i]: {"min": None, "max": None, "nulls": 0} for i in idx}
            for n, row in enumerate(reader, start=2):
                for i in idx:
                    s = col_stats[header[i]]
                    if row[i] == "":
                        s["nulls"] += 1
                        continue
                    try:
                        row[i] = shift_value(row[i], days)
                    except ValueError as e:
                        raise ShiftError(f"{table}.csv line {n} column {header[i]}: {e}") from e
                    stats["cells_shifted"] += 1
                    s["min"] = row[i] if s["min"] is None or row[i] < s["min"] else s["min"]
                    s["max"] = row[i] if s["max"] is None or row[i] > s["max"] else s["max"]
                if writer:
                    writer.writerow(row)
                stats["rows"][table] = stats["rows"].get(table, 0) + 1
            stats["rows"].setdefault(table, 0)
            stats["columns"][table] = col_stats
        finally:
            if out_fh:
                out_fh.close()


def shift_directory(src: Path, out: Path, days: int, tables, schema_sql: str, dry_run: bool,
                    allow_reshift: bool = False) -> dict:
    src, out = Path(src), Path(out)
    _check_paths(src, out, allow_reshift)
    date_cols = date_columns_from_schema(schema_sql)
    known = all_columns_from_schema(schema_sql)
    names = _tables_in(src, tables)
    missing = [t for t in names if not (src / f"{t}.csv").is_file()]
    if missing:
        raise ShiftError(f"missing input CSVs: {missing}")
    stats: dict = {"cells_shifted": 0, "rows": {}, "columns": {}}
    if not dry_run:
        out.mkdir(parents=True, exist_ok=True)
    for table in names:
        _shift_table(src, table, date_cols.get(table, set()), known.get(table), days,
                     None if dry_run else out / f"{table}.csv", stats)
    hits = scan_text_dates(src, date_cols, names)
    stats["text_date_columns"] = {f"{t}.{c}": {"examples": ex, "decision": TEXT_COLUMN_DECISIONS.get(
        (t, c), "UNEXPLAINED — review before using the output")} for (t, c), ex in hits.items()}
    stats["not_shifted_invariants"] = {f"{t}.{c}": why for (t, c), why in INVARIANT_COLUMNS.items() if t in names}
    stats["ignored_files"] = sorted(p.name for p in src.iterdir() if p.is_file() and p.stem not in names
                                    and p.name != MANIFEST)
    if not dry_run:
        manifest = {"days": days, "source": str(src.resolve()), "tables": names,
                    "date_columns": {t: sorted(date_cols.get(t, set())) for t in names},
                    "cells_shifted": stats["cells_shifted"], "rows": stats["rows"]}
        (out / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--days", type=int, default=63)
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument("--allow-non-weekly", action="store_true", help="allow --days not divisible by 7")
    args = ap.parse_args(argv)
    if args.days % 7 and not args.allow_non_weekly:
        ap.error(f"--days {args.days} is not a multiple of 7: weekday patterns would break")
    schema_sql = "\n".join(p.read_text(encoding="utf-8") for p in SCHEMA_FILES)
    try:
        stats = shift_directory(args.input, args.output, args.days, LOAD_ORDER, schema_sql, args.dry_run)
    except ShiftError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    json.dump(stats, sys.stdout, indent=2)
    print()
    unexplained = [k for k, v in stats["text_date_columns"].items() if v["decision"].startswith("UNEXPLAINED")]
    if unexplained:
        print(f"ERROR: unexplained date-like text columns: {unexplained}", file=sys.stderr)
        return 1
    print(f"{'DRY RUN — ' if args.dry_run else ''}shifted {stats['cells_shifted']} cells by {args.days} days"
          f"{'' if args.dry_run else ' -> ' + str(args.output)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
