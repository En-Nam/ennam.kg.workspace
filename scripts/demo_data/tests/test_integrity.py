"""Every CSV must load into pharmacy_demo with its PK/FK constraints (schema/base.sql + schema/extension.sql)."""
import re

from helpers import FOREIGN_KEYS, PRIMARY_KEYS


def test_primary_keys_are_unique(out):
    for table, pk in PRIMARY_KEYS.items():
        values = [r[pk] for r in out.rows(table)]
        assert len(values) == len(set(values)), f"duplicate {table}.{pk}"
        assert all(values), f"empty {table}.{pk}"


def test_foreign_keys_resolve(out):
    for table, column, ref in FOREIGN_KEYS:
        keys = {r[PRIMARY_KEYS[ref]] for r in out.rows(ref)}
        dangling = {r[column] for r in out.rows(table) if r[column] and r[column] not in keys}
        assert not dangling, f"{table}.{column} -> {ref}: {sorted(dangling)[:5]}"


def test_write_test_leftovers_are_gone(out):
    assert all(re.fullmatch(r"TXN-\d{7}", r["transaction_id"]) for r in out.rows("transactions"))
    assert "EMP-9999" not in {r["employee_id"] for r in out.rows("employees")}
    assert "EMP-9999" not in {r["printed_by_employee_id"] for r in out.rows("receipts")}
    assert not {"CUS-99991", "CUS-99992", "CUS-99993"} & {r["customer_id"] for r in out.rows("customers")}


def test_new_columns_are_appended_last(out, base):
    assert out.columns("employees") == base.columns("employees") + ["hourly_wage"]
    assert out.columns("prescriptions") == base.columns("prescriptions") + ["acquisition_cost"]
    assert all(float(r["hourly_wage"]) > 0 for r in out.rows("employees"))
