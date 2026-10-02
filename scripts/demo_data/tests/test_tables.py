from datetime import date, datetime

import pytest

from conftest import BASE_DIR
from pharmacy_demo_gen.tables import IdSeq, Table, fmt, load_base, read_table, write_table


def test_fmt_matches_original_csv_conventions():
    assert fmt(None) == ""
    assert fmt(True) == "True" and fmt(False) == "False"
    assert fmt(3.14159) == "3.14"
    assert fmt(7) == "7"
    assert fmt(datetime(2026, 7, 31, 9, 5, 0)) == "2026-07-31 09:05:00"
    assert fmt(date(2026, 7, 31)) == "2026-07-31"


def test_id_sequences_start_outside_the_original_range():
    seq = IdSeq("TXN-", 7, 1_000_001)
    assert [seq.next(), seq.next()] == ["TXN-1000001", "TXN-1000002"]


def test_table_rejects_unknown_columns():
    with pytest.raises(KeyError):
        Table(["a"]).add({"b": 1})


def test_write_then_read_roundtrip_uses_lf(tmp_path):
    table = Table(["id", "note"])
    table.add({"id": "X-1", "note": 'a, "quoted" value'})
    write_table(tmp_path / "x.csv", table)
    assert read_table(tmp_path / "x.csv").rows == table.rows
    assert b"\r" not in (tmp_path / "x.csv").read_bytes()


def test_load_base_drops_write_test_leftovers():
    tables = load_base(BASE_DIR)
    receipt_ids = {r["receipt_id"] for r in tables["receipts"].rows}
    assert not {"RCT-0005317", "RCT-0005319", "RCT-0005328"} & receipt_ids
    assert len(tables["receipts"].rows) == 5342
    assert len(tables["transactions"].rows) == 5000
