from datetime import date

import pytest

from conftest import BASE_DIR
from pharmacy_demo_gen import config as C
from pharmacy_demo_gen.catalog import build_vendors, prepare_catalog
from pharmacy_demo_gen.ctx import Ctx
from pharmacy_demo_gen.inventory import simulate_inventory
from pharmacy_demo_gen.tables import load_base, parse_dt


@pytest.fixture(scope="module")
def staged():
    c = Ctx(load_base(BASE_DIR))
    prepare_catalog(c)
    vendors = build_vendors(c)
    orders, lines = simulate_inventory(c, vendors)
    return c, vendors, orders, lines


def test_receipt_movements_reference_purchase_orders(staged):
    c, _, orders, lines = staged
    po_ids = {o["po_id"] for o in orders.rows}
    receipts = [m for m in c.t["inventory_movements"].rows if m["movement_type"] == "RECEIPT"]
    assert len(receipts) == len(lines.rows) > 0
    assert all(m["reference_id"] in po_ids and int(m["quantity_change"]) > 0 for m in receipts)


def test_purchase_order_lead_time_matches_vendor(staged):
    _, vendors, orders, _ = staged
    lead = {v["vendor_id"]: int(v["lead_time_days"]) for v in vendors.rows}
    for o in orders.rows:
        days = (parse_dt(o["received_datetime"]).date() - date.fromisoformat(o["order_date"])).days
        assert days in (lead[o["vendor_id"]], lead[o["vendor_id"]] + 1)


def test_weekly_snapshots_on_fridays_with_variances_until_june_only(staged):
    c, _, _, _ = staged
    generated = [s for s in c.t["inventory_snapshots"].rows if s["snapshot_id"].startswith("SNP-1")]
    assert len(generated) == 52 * 1500
    assert all(date.fromisoformat(s["snapshot_date"]).weekday() == 4 for s in generated)
    july = [s for s in generated if date.fromisoformat(s["snapshot_date"]) >= C.COUNT_VARIANCE_END]
    assert july and all(s["variance_quantity"] == "0" for s in july)
    may_june = [s for s in generated
                if C.CORE_START <= date.fromisoformat(s["snapshot_date"]) < C.COUNT_VARIANCE_END]
    share = sum(s["variance_quantity"] != "0" for s in may_june) / len(may_june)
    assert 0.12 <= share <= 0.24, share


def test_history_count_adjustments_mirror_snapshot_variances(staged):
    c, _, _, _ = staged
    variances = [s for s in c.t["inventory_snapshots"].rows
                 if s["snapshot_id"].startswith("SNP-1") and s["variance_quantity"] != "0"]
    adjustments = [a for a in c.t["inventory_adjustments"].rows if a["adjustment_id"].startswith("ADJ-1")]
    assert len(adjustments) == len(variances) > 0
