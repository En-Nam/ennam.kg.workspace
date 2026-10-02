from collections import defaultdict
from datetime import date

import pytest

from conftest import BASE_DIR
from pharmacy_demo_gen import config as C
from pharmacy_demo_gen.catalog import build_vendors, prepare_catalog
from pharmacy_demo_gen.ctx import Ctx
from pharmacy_demo_gen.inventory import _weekly_count, simulate_inventory
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
    adjustments = [a for a in c.t["inventory_adjustments"].rows
                   if a["adjustment_id"].startswith("ADJ-1") and a["adjustment_type"] != "Stock correction"]
    assert len(adjustments) == len(variances) > 0


def test_no_snapshot_has_negative_on_hand(staged):
    c, _, _, _ = staged
    bad = [s["snapshot_id"] for s in c.t["inventory_snapshots"].rows
           if int(s["system_quantity"]) < 0 or int(s["counted_quantity"]) < 0]
    assert not bad, bad[:5]


def test_snapshot_arithmetic_chains_through_movements_and_adjustments(staged):
    c, _, _, _ = staged
    snaps = defaultdict(list)
    for s in c.t["inventory_snapshots"].rows:
        if s["snapshot_id"].startswith("SNP-1"):
            snaps[(s["store_id"], s["product_id"])].append(s)
    net = defaultdict(list)  # (store, product) -> [(date, qty)]
    for m in c.t["inventory_movements"].rows:
        day = parse_dt(m["movement_datetime"]).date()
        net[(m["store_id"], m["product_id"])].append((day, int(m["quantity_change"])))
    for a in c.t["inventory_adjustments"].rows:
        if a["adjustment_id"].startswith("ADJ-1") and a["adjustment_type"] != "Stock correction":
            continue  # weekly count corrections: already represented by counted_quantity - system_quantity
        day = parse_dt(a["adjustment_datetime"]).date()
        net[(a["store_id"], a["product_id"])].append((day, int(a["adjustment_quantity"])))
    checked = 0
    for key, rows in snaps.items():
        rows = sorted(rows, key=lambda r: r["snapshot_date"])
        for prev, cur in zip(rows, rows[1:]):
            lo, hi = date.fromisoformat(prev["snapshot_date"]), date.fromisoformat(cur["snapshot_date"])
            between = sum(q for d, q in net[key] if lo < d <= hi)
            assert int(cur["system_quantity"]) == int(prev["counted_quantity"]) + between, (key, lo, hi)
            checked += 1
    assert checked == 51 * 1500


def test_expected_date_is_order_date_plus_vendor_lead_time(staged):
    _, vendors, orders, _ = staged
    lead = {v["vendor_id"]: int(v["lead_time_days"]) for v in vendors.rows}
    for o in orders.rows:
        gap = date.fromisoformat(o["expected_date"]) - date.fromisoformat(o["order_date"])
        assert gap.days == lead[o["vendor_id"]]


def test_po_line_quantity_matches_receipt_movement(staged):
    c, _, _, lines = staged
    receipts = {(m["reference_id"], m["product_id"]): int(m["quantity_change"])
                for m in c.t["inventory_movements"].rows if m["movement_type"] == "RECEIPT"}
    assert len(receipts) == len(lines.rows)
    assert all(receipts[(ln["po_id"], ln["product_id"])] == int(ln["quantity"]) for ln in lines.rows)


def test_receipts_do_not_postdate_as_of(staged):
    c, _, orders, _ = staged
    assert all(parse_dt(o["received_datetime"]).date() <= C.HISTORY_END for o in orders.rows)
    assert all(parse_dt(m["movement_datetime"]).date() <= C.HISTORY_END
               for m in c.t["inventory_movements"].rows if m["movement_type"] == "RECEIPT")


def test_same_seed_produces_identical_frames(staged):
    c, vendors, orders, lines = staged
    c2 = Ctx(load_base(BASE_DIR))
    prepare_catalog(c2)
    o2, l2 = simulate_inventory(c2, build_vendors(c2))
    assert orders.rows == o2.rows and lines.rows == l2.rows
    for name in ("inventory_snapshots", "inventory_adjustments", "inventory_movements"):
        assert c.t[name].rows == c2.t[name].rows


def _generated_adjustments(c):
    return [a for a in c.t["inventory_adjustments"].rows if a["adjustment_id"].startswith("ADJ-1")]


def test_no_generated_shrinkage_or_expiration_in_july(staged):
    c, _, _, _ = staged
    late = [a for a in _generated_adjustments(c)
            if parse_dt(a["adjustment_datetime"]).date() >= C.COUNT_VARIANCE_END]
    assert all(a["adjustment_type"] == "Stock correction" for a in late)
    assert not [a for a in _generated_adjustments(c) if a["adjustment_type"] == "Expiration"]


def test_floor_rows_are_stock_corrections_that_bring_book_to_zero(staged):
    c, _, _, _ = staged
    floors = [a for a in _generated_adjustments(c) if a["adjustment_type"] not in ("Shrinkage", "Cycle Count")]
    assert floors
    assert all(a["adjustment_type"] == "Stock correction" and a["reason"] == "Opening-stock correction"
               and a["quantity_after"] == "0" and int(a["adjustment_quantity"]) < 0
               and str(a["flagged"]) == "False" for a in floors)


def test_count_variance_that_would_go_negative_is_forced_to_zero():
    class Rng:
        def random(self):
            return 0.0  # always draws a variance

        def choice(self, _):
            return 1  # +1 would make system_quantity = 0 - 1

    stub = type("Stub", (), {"rng": Rng()})()
    snapshots, adjustments = [], []
    before = _weekly_count(stub, ("PH-001", "PRD-00001"), date(2026, 6, 5), 0, snapshots, adjustments)
    assert before == 0 and not adjustments
    assert snapshots == [(date(2026, 6, 5), "PH-001", "PRD-00001", 0, 0)]
