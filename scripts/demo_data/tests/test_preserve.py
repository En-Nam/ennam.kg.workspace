"""The original May-Jul 2026 package is the verified ground truth: its rows must survive unchanged."""
from helpers import PRIMARY_KEYS, is_generated

# Only deliberate value changes to original rows (see plan "Thay đổi trên dữ liệu gốc").
REBASED_PRODUCT_COLUMNS = {"unit_cost", "retail_price", "gross_margin_percent"}
DROPPED = {"RCT-0005317", "RCT-0005319", "RCT-0005328"}  # write-test leftovers in receipts.csv


def test_original_rows_are_kept_verbatim(out, base):
    for table, pk in PRIMARY_KEYS.items():
        if table in ("vendors", "product_costs", "purchase_orders", "purchase_order_lines"):
            continue
        generated = {r[pk]: r for r in out.rows(table)}
        for original in base.rows(table):
            if original[pk] in DROPPED:
                assert original[pk] not in generated
                continue
            row = generated.get(original[pk])
            assert row is not None, f"{table} lost {original[pk]}"
            rebased = table == "products" and original["prescription_required"] == "True"
            skip = REBASED_PRODUCT_COLUMNS if rebased else set()
            changed = {c for c in base.columns(table) if c not in skip and row[c] != original[c]}
            assert not changed, f"{table} {original[pk]} changed {sorted(changed)}"


def test_rx_products_are_priced_per_dispensing_unit(out):
    rx = [p for p in out.rows("products") if p["prescription_required"] == "True"]
    assert len(rx) == 74
    assert all(0 < float(p["unit_cost"]) < 5 for p in rx), "Rx unit_cost must be per unit, not per package"


def test_generated_rx_cost_is_about_80_percent_of_paid(out):
    claims = {c["prescription_id"]: c for c in out.rows("insurance_claims")}
    paid = cost = 0.0
    for rx in out.rows("prescriptions"):
        claim = claims[rx["prescription_id"]]
        if is_generated(rx["prescription_id"]) and claim["claim_status"] == "Approved" \
                and rx["store_id"] != "PH-003":
            paid += float(claim["approved_amount"]) + float(claim["customer_amount"])
            cost += float(rx["acquisition_cost"])
    assert 0.78 <= cost / paid <= 0.82
