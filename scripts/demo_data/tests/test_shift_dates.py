"""shift_dates.py moves every date/timestamp of the 25 loader CSVs by N days and nothing else.
Why it matters: the planted findings are judged on rolling windows ending at the as-of date and on
same-weekday baselines, so a shift is only safe if it is uniform, a multiple of 7, and byte-exact elsewhere."""
import csv
import json
from datetime import date
from pathlib import Path

import pytest

import shift_dates as S

WORKSPACE = Path(__file__).resolve().parents[3]
REAL_DATA = WORKSPACE / "demo_mockdata"
SCHEMA = [Path(__file__).resolve().parents[1] / "schema" / n for n in ("base.sql", "extension.sql")]

EXPECTED_DATE_COLUMNS = {
    "audit_events": {"event_datetime"}, "cash_drawers": {"opened_at", "closed_at"},
    "customers": {"signup_date"}, "discount_overrides": {"override_datetime"},
    "employee_shifts": {"scheduled_start", "scheduled_end", "actual_clock_in", "actual_clock_out"},
    "employees": {"hire_date"}, "insurance_claims": {"submitted_datetime", "resolved_datetime"},
    "inventory_adjustments": {"adjustment_datetime"}, "inventory_movements": {"movement_datetime"},
    "inventory_snapshots": {"snapshot_date"}, "invoices": {"issued_datetime", "due_date", "paid_date"},
    "payments": {"payment_datetime"},
    "prescriptions": {"received_datetime", "filled_datetime", "picked_up_datetime"},
    "receipts": {"printed_datetime"}, "refunds": {"refund_datetime"}, "stores": {"opening_date"},
    "transactions": {"transaction_datetime"}, "voids": {"void_datetime"},
    "product_costs": {"effective_from", "effective_to"},
    "purchase_orders": {"order_date", "expected_date", "received_datetime"},
}


def schema_text() -> str:
    return "\n".join(p.read_text() for p in SCHEMA)


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


# --- column typing comes from the schema, never from content ---------------------------------

def test_date_columns_are_derived_from_schema_types():
    cols = S.date_columns_from_schema(schema_text())
    assert {t: c for t, c in cols.items() if c} == EXPECTED_DATE_COLUMNS


def test_schema_parser_sees_extension_add_column_and_ignores_text_columns():
    sql = ("CREATE TABLE public.a (\n    id text NOT NULL,\n    d date,\n    t timestamp without time zone\n);\n"
           "ALTER TABLE public.a ADD COLUMN extra_ts timestamp;\nALTER TABLE public.a ADD COLUMN note text;\n")
    assert S.date_columns_from_schema(sql)["a"] == {"d", "t", "extra_ts"}


# --- value shifting ---------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("2026-07-31", "2026-10-02"),
    ("2026-07-31 21:05:22", "2026-10-02 21:05:22"),
    ("2025-12-31 23:59:59", "2026-03-04 23:59:59"),
    ("", ""),
])
def test_shift_value_moves_only_the_date_part(value, expected):
    assert S.shift_value(value, 63) == expected


def test_shift_value_rejects_non_iso_content_in_a_date_column():
    with pytest.raises(ValueError):
        S.shift_value("31/07/2026", 63)


def test_shift_by_non_multiple_of_7_is_refused_by_default(tmp_path):
    with pytest.raises(SystemExit):
        S.main(["--input", str(tmp_path), "--output", str(tmp_path / "o"), "--days", "10", "--dry-run"])


# --- directory behaviour -------------------------------------------------------------------

@pytest.fixture
def mini_input(tmp_path) -> Path:
    src = tmp_path / "in"
    src.mkdir()
    write_csv(src / "stores.csv", ["store_id", "store_name", "opening_date", "status"],
              [["PH-001", "Downtown", "2018-02-15", "Active"]])
    write_csv(src / "refunds.csv", ["refund_id", "refund_datetime", "days_after_purchase", "flag_reason"],
              [["REF-1", "2026-07-26 20:26:00", "22", "No receipt; After 8 PM"], ["REF-2", "", "3", ""]])
    write_csv(src / "invoices.csv", ["invoice_id", "invoice_number", "issued_datetime", "due_date", "paid_date"],
              [["INV-1", "2026-000001", "2026-05-01 23:38:38", "2026-05-31", ""]])
    return src


def run(src: Path, out: Path, *extra: str) -> dict:
    return S.shift_directory(src, out, days=63, tables=None, schema_sql=schema_text(), dry_run="--dry-run" in extra)


def test_shift_directory_rewrites_only_date_cells(mini_input, tmp_path):
    out = tmp_path / "out"
    report = run(mini_input, out)
    rows = list(csv.reader((out / "refunds.csv").open()))
    assert rows[1] == ["REF-1", "2026-09-27 20:26:00", "22", "No receipt; After 8 PM"]
    assert rows[2] == ["REF-2", "", "3", ""]
    inv = list(csv.reader((out / "invoices.csv").open()))[1]
    assert inv == ["INV-1", "2026-000001", "2026-07-03 23:38:38", "2026-08-02", ""]
    assert report["cells_shifted"] == 4  # opening_date, refund_datetime, issued, due


def test_manifest_blocks_double_shift(mini_input, tmp_path):
    out = tmp_path / "out"
    run(mini_input, out)
    manifest = json.loads((out / S.MANIFEST).read_text())
    assert manifest["days"] == 63
    with pytest.raises(S.ShiftError, match="already shifted"):
        run(out, tmp_path / "again")


def test_refuses_existing_non_empty_output_and_in_place(mini_input, tmp_path):
    out = tmp_path / "out"
    run(mini_input, out)
    with pytest.raises(S.ShiftError, match="not empty"):
        run(mini_input, out)
    with pytest.raises(S.ShiftError, match="same directory"):
        run(mini_input, mini_input)


def test_refuses_to_write_into_demo_mockdata(mini_input):
    with pytest.raises(S.ShiftError, match="demo_mockdata"):
        run(mini_input, REAL_DATA / "shifted_here")


def test_dry_run_writes_nothing(mini_input, tmp_path):
    out = tmp_path / "out"
    report = run(mini_input, out, "--dry-run")
    assert not out.exists()
    assert report["cells_shifted"] == 4  # opening_date, refund_datetime, issued, due


def test_unknown_csv_column_fails_loudly(mini_input, tmp_path):
    write_csv(mini_input / "voids.csv", ["void_id", "void_when"], [["V1", "2026-01-01"]])
    with pytest.raises(S.ShiftError, match="void_when"):
        run(mini_input, tmp_path / "out")


def test_scan_reports_date_like_text_in_non_date_columns(mini_input):
    hits = S.scan_text_dates(mini_input, S.date_columns_from_schema(schema_text()))
    assert ("invoices", "invoice_number") in hits
    assert ("refunds", "flag_reason") not in hits


# --- the real 25-table package ----------------------------------------------------------------

@pytest.fixture(scope="module")
def real_shift(tmp_path_factory):
    if not (REAL_DATA / "transactions.csv").exists():
        pytest.skip("demo_mockdata not present")
    out = tmp_path_factory.mktemp("shifted") / "out"
    report = S.shift_directory(REAL_DATA, out, days=63, tables=S.LOAD_ORDER, schema_sql=schema_text(), dry_run=False)
    return out, report


def _pairs(table: str, out: Path):
    with (REAL_DATA / f"{table}.csv").open(newline="") as a, (out / f"{table}.csv").open(newline="") as b:
        ra, rb = csv.reader(a), csv.reader(b)
        header = next(ra)
        assert next(rb) == header
        for old, new in zip(ra, rb, strict=True):
            yield header, old, new


def test_real_package_weekday_and_time_of_day_unchanged(real_shift):
    out, report = real_shift
    cols = S.date_columns_from_schema(schema_text())
    checked = 0
    for table in S.LOAD_ORDER:
        for header, old, new in _pairs(table, out):
            for i, name in enumerate(header):
                if name in cols.get(table, set()) and old[i]:
                    o, n = date.fromisoformat(old[i][:10]), date.fromisoformat(new[i][:10])
                    assert (n - o).days == 63 and n.weekday() == o.weekday(), (table, name, old[i], new[i])
                    assert new[i][10:] == old[i][10:]
                    checked += 1
                else:
                    assert new[i] == old[i], (table, name)
    assert checked == report["cells_shifted"] > 400_000


def test_real_package_round_trips_byte_for_byte(real_shift, tmp_path):
    out, _ = real_shift
    back = tmp_path / "back"
    S.shift_directory(out, back, days=-63, tables=S.LOAD_ORDER, schema_sql=schema_text(), dry_run=False,
                      allow_reshift=True)
    for table in S.LOAD_ORDER:
        assert (back / f"{table}.csv").read_bytes() == (REAL_DATA / f"{table}.csv").read_bytes(), table


def test_real_package_window_ends_2026_10_02(real_shift):
    out, _ = real_shift
    with (out / "transactions.csv").open(newline="") as fh:
        days = [r["transaction_datetime"][:10] for r in csv.DictReader(fh)]
    assert min(days) == "2025-10-03" and max(days) == "2026-10-02"


def test_real_invoice_number_year_prefix_still_matches_issue_year(real_shift):
    out, _ = real_shift
    with (out / "invoices.csv").open(newline="") as fh:
        bad = [r for r in csv.DictReader(fh) if r["invoice_number"][:4] != r["issued_datetime"][:4]]
    assert not bad, bad[:3]


def test_real_days_after_purchase_still_equals_refund_minus_sale_day(real_shift):
    """days_after_purchase is a delta: a uniform shift must leave it consistent with the shifted dates."""
    out, _ = real_shift

    def check(base: Path) -> list:
        with (base / "transactions.csv").open(newline="") as fh:
            sale = {r["transaction_id"]: r["transaction_datetime"][:10] for r in csv.DictReader(fh)}
        with (base / "refunds.csv").open(newline="") as fh:
            return [(date.fromisoformat(r["refund_datetime"][:10])
                     - date.fromisoformat(sale[r["original_transaction_id"]])).days - int(r["days_after_purchase"])
                    for r in csv.DictReader(fh) if r["original_transaction_id"] in sale]

    assert check(out) == check(REAL_DATA)


def test_real_po_order_weekday_relation_unchanged(real_shift):
    """vendors.order_weekday is a weekday number, not a date: it must still describe the same PO weekdays."""
    out, _ = real_shift

    def weekdays(base: Path) -> list:
        with (base / "purchase_orders.csv").open(newline="") as fh:
            return [date.fromisoformat(r["order_date"]).weekday() for r in csv.DictReader(fh)]

    assert weekdays(out) == weekdays(REAL_DATA)


def test_real_scan_finds_only_explained_text_columns(real_shift):
    hits = S.scan_text_dates(REAL_DATA, S.date_columns_from_schema(schema_text()), tables=S.LOAD_ORDER)
    assert set(hits) <= set(S.TEXT_COLUMN_DECISIONS), set(hits) - set(S.TEXT_COLUMN_DECISIONS)
