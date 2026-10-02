"""FND-009: acquisition cost +8% on 5 Rx drugs at PH-003 from 2026-07-18, reimbursement flat.
Robust signals are ratio-type (margin %) and per-unit gap; store-level additive $ is volume-noisy (see plan)."""
from datetime import date

from helpers import STORES, is_generated, within

RECENT = (date(2026, 7, 18), date(2026, 7, 31))
PRIOR = (date(2026, 6, 20), date(2026, 7, 17))


def _plant_drugs(out) -> set[str]:
    return {r["product_id"] for r in out.rows("product_costs") if r["store_id"] == "PH-003"}


def _rx_totals(out, store, window, products=None, generated_only=False):
    claims = {c["prescription_id"]: c for c in out.rows("insurance_claims")}
    acc = {"revenue": 0.0, "payer": 0.0, "cost": 0.0, "units": 0}
    for rx in out.rows("prescriptions"):
        claim = claims[rx["prescription_id"]]
        if rx["store_id"] != store or not within(rx["received_datetime"], *window):
            continue
        if rx["status"] in ("Reversed", "Cancelled") or claim["claim_status"] != "Approved":
            continue
        if products is not None and rx["product_id"] not in products:
            continue
        if generated_only and not is_generated(rx["prescription_id"]):
            continue
        acc["revenue"] += float(claim["approved_amount"]) + float(claim["customer_amount"])
        acc["payer"] += float(claim["approved_amount"])
        acc["cost"] += float(rx["acquisition_cost"])
        acc["units"] += int(rx["quantity"])
    return acc


def test_cost_history_plants_exactly_five_drugs_at_ph003(out):
    rows = [r for r in out.rows("product_costs") if r["store_id"]]
    assert len(rows) == 5
    assert {r["store_id"] for r in rows} == {"PH-003"}
    assert {r["effective_from"] for r in rows} == {"2026-07-18"}
    chain = {r["product_id"]: float(r["unit_cost"]) for r in out.rows("product_costs")
             if not r["store_id"] and r["effective_from"] == "2026-01-01"}
    for r in rows:
        assert abs(float(r["unit_cost"]) / chain[r["product_id"]] - 1.08) < 0.001


def test_ph003_margin_pct_drops_others_flat(out):
    change = {}
    for s in STORES:
        a, b = _rx_totals(out, s, RECENT), _rx_totals(out, s, PRIOR)
        change[s] = ((a["revenue"] - a["cost"]) / a["revenue"]) / ((b["revenue"] - b["cost"]) / b["revenue"]) - 1
    assert change["PH-003"] <= -0.08, change
    assert all(abs(change[s]) <= 0.02 for s in STORES if s != "PH-003"), change


def test_plant_drugs_drive_the_drop(out):
    drugs = _plant_drugs(out)
    recent = _rx_totals(out, "PH-003", RECENT)
    planted = _rx_totals(out, "PH-003", RECENT, drugs)
    assert planted["cost"] / recent["cost"] >= 0.25, "5 drugs must carry a large share of PH-003 Rx cost"
    before = _rx_totals(out, "PH-003", PRIOR, drugs)
    gap_now = (planted["payer"] - planted["cost"]) / planted["units"]
    gap_before = (before["payer"] - before["cost"]) / before["units"]
    assert gap_now / gap_before - 1 <= -0.40


def test_reimbursement_stays_flat_for_plant_drugs(out):
    for drug in sorted(_plant_drugs(out)):
        now = _rx_totals(out, "PH-003", RECENT, {drug}, generated_only=True)
        before = _rx_totals(out, "PH-003", PRIOR, {drug}, generated_only=True)
        per_unit_change = (now["revenue"] / now["units"]) / (before["revenue"] / before["units"]) - 1
        assert abs(per_unit_change) <= 0.03, (drug, per_unit_change)
