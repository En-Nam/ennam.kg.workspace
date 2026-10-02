import pytest

from conftest import BASE_DIR
from pharmacy_demo_gen import config as C
from pharmacy_demo_gen.catalog import prepare_catalog
from pharmacy_demo_gen.ctx import Ctx
from pharmacy_demo_gen.operations import generate_refunds, generate_shifts
from pharmacy_demo_gen.retail import generate_sales
from pharmacy_demo_gen.tables import load_base, parse_dt


@pytest.fixture(scope="module")
def staged():
    c = Ctx(load_base(BASE_DIR))
    prepare_catalog(c)
    sales = generate_sales(c)
    generate_refunds(c, sales)
    generate_shifts(c)
    return c, sales


def test_history_starts_on_first_day_and_stays_in_window(staged):
    _, sales = staged
    assert min(s["day"] for s in sales) == C.HISTORY_START
    assert max(s["day"] for s in sales) <= C.HISTORY_END


def test_window_topups_are_weekend_only_and_skip_planted_people(staged):
    _, sales = staged
    topups = [s for s in sales if s["day"] >= C.CORE_START]
    assert topups and {s["day"].weekday() for s in topups} <= {4, 5, 6}
    assert not [s for s in topups if s["cashier"] in C.PLANTED_PEOPLE]


def test_generated_transaction_totals_add_up(staged):
    c, _ = staged
    for t in c.t["transactions"].rows:
        if t["transaction_id"].startswith("TXN-1"):
            expected = float(t["subtotal"]) - float(t["discount_amount"]) + float(t["tax_amount"])
            assert abs(float(t["total_amount"]) - expected) <= 0.011, t["transaction_id"]


def test_exception_rows_are_generated_only_before_the_original_window(staged):
    c, _ = staged
    checks = [("refunds", "refund_id", "refund_datetime", "REF-1"), ("voids", "void_id", "void_datetime", "VOID-1"),
              ("discount_overrides", "override_id", "override_datetime", "OVR-1"),
              ("cash_drawers", "drawer_session_id", "opened_at", "DRW-1"),
              ("employee_shifts", "shift_id", "scheduled_start", "SHF-1")]
    for table, pk, col, prefix in checks:
        generated = [r for r in c.t[table].rows if r[pk].startswith(prefix)]
        assert generated, table
        assert all(parse_dt(r[col]).date() < C.CORE_START for r in generated), table


def test_each_generated_sale_is_refunded_at_most_once(staged):
    c, _ = staged
    originals = [r["original_transaction_id"] for r in c.t["refunds"].rows if r["refund_id"].startswith("REF-1")]
    assert len(originals) == len(set(originals))
