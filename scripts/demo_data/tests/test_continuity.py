"""No step change on 2026-05-01: the generated history must look like the original window it is glued to."""
import calendar
from collections import Counter, defaultdict
from statistics import mean

from helpers import CORE_START, STORES, day_of

PLANTED_APPROVER = "EMP-0023"


def _sales(out):
    net, count = defaultdict(float), Counter()
    for t in out.rows("transactions"):
        value = float(t["subtotal"]) - float(t["discount_amount"])
        net[(t["store_id"], t["transaction_datetime"][:7])] += value
        period = "history" if day_of(t["transaction_datetime"]) < CORE_START else "original"
        net[(t["store_id"], period)] += value
        count[(t["store_id"], period)] += 1
    return net, count


def test_history_basket_size_matches_original_window(out):
    net, count = _sales(out)
    for s in STORES:
        hist = net[(s, "history")] / count[(s, "history")]
        orig = net[(s, "original")] / count[(s, "original")]
        assert abs(hist / orig - 1) <= 0.05, (s, round(hist, 1), round(orig, 1))


def test_april_to_may_sales_have_no_step(out):
    """Net sales PER DAY (April has 30 days, May 31) across the history/original boundary."""
    net, _ = _sales(out)
    for s in STORES:
        change = (net[(s, "2026-05")] / 31) / (net[(s, "2026-04")] / 30) - 1
        assert abs(change) <= 0.10, (s, round(change, 3))


def test_override_rate_continues_into_original_window(out):
    _, count = _sales(out)
    overrides = Counter()
    for o in out.rows("discount_overrides"):
        if o["approving_manager_id"] != PLANTED_APPROVER:
            period = "history" if day_of(o["override_datetime"]) < CORE_START else "original"
            overrides[(o["store_id"], period)] += 1
    for s in STORES:
        orig = overrides[(s, "original")] / count[(s, "original")]
        hist = overrides[(s, "history")] / count[(s, "history")]
        assert 0.02 <= hist <= 0.07, (s, hist)
        if orig > 0:  # PH-002: every original override is the EMP-0023 plant
            assert abs(hist / orig - 1) <= 0.25, (s, round(hist, 4), round(orig, 4))


def test_shrink_continues_through_may_and_june(out):
    acc = defaultdict(float)
    for a in out.rows("inventory_adjustments"):
        if a["adjustment_type"] == "Shrinkage":
            acc[(a["store_id"], a["adjustment_datetime"][:7])] += -float(a["adjustment_value"])
    for s in STORES:
        baseline = mean(acc[(s, m)] for m in ("2026-01", "2026-02", "2026-03", "2026-04"))
        for month in ("2026-05", "2026-06"):
            assert abs(acc[(s, month)] / baseline - 1) <= 0.40, (s, month)


def test_sales_per_day_never_collapse_month_to_month(out):
    net, _ = _sales(out)
    months = sorted({m for (_, m) in net if m[:2] == "20" and m <= "2026-06"})

    def per_day(s, m):
        return net[(s, m)] / calendar.monthrange(int(m[:4]), int(m[5:]))[1]

    for s in STORES:
        for prev, cur in zip(months, months[1:]):
            assert per_day(s, cur) / per_day(s, prev) - 1 >= -0.15, (s, prev, cur)


def test_rx_cost_ratio_has_no_step_at_boundary(out):
    """Rx acquisition cost / paid must look alike on both sides of 2026-05-01 (PH-003 excluded: margin plant)."""
    claims = {c["prescription_id"]: c for c in out.rows("insurance_claims")}
    acc = defaultdict(lambda: [0.0, 0.0])
    for rx in out.rows("prescriptions"):
        claim = claims[rx["prescription_id"]]
        if rx["store_id"] == "PH-003" or claim["claim_status"] != "Approved":
            continue
        period = "history" if day_of(rx["received_datetime"]) < CORE_START else "original"
        acc[period][0] += float(rx["acquisition_cost"])
        acc[period][1] += float(claim["approved_amount"]) + float(claim["customer_amount"])
    ratios = {k: v[0] / v[1] for k, v in acc.items()}
    assert abs(ratios["history"] / ratios["original"] - 1) <= 0.05, ratios
