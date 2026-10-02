"""FND-001..FND-008 must still trigger on the 12-month data, and nothing else may look like them.
Thresholds are PROXIES (the real rules live in Plan D); each asserts with headroom above the request's 2.5x."""
from collections import Counter, defaultdict
from datetime import date, timedelta

from helpers import AS_OF, CORE_START, STORES, day_of, ts, within

LAST_30 = (AS_OF - timedelta(days=29), AS_OF)
LAST_90 = (AS_OF - timedelta(days=89), AS_OF)


def _history_months(rows, col):
    return {r[col][:7] for r in rows if day_of(r[col]) < CORE_START}


def test_fnd001_sarah_refund_rate_far_above_peers(out):
    sales = Counter(r["employee_id"] for r in out.rows("transactions") if within(r["transaction_datetime"], *LAST_30))
    refunds = Counter(r["employee_id"] for r in out.rows("refunds") if within(r["refund_datetime"], *LAST_30))
    rate = {e: refunds[e] / n for e, n in sales.items()}
    peers = [v for e, v in rate.items() if e != "EMP-0006"]
    assert refunds["EMP-0006"] >= 10
    assert rate["EMP-0006"] >= 3 * (sum(peers) / len(peers))
    assert all(n < 10 for e, n in refunds.items() if e != "EMP-0006")


def test_fnd001_no_refund_outlier_in_history(out):
    rows = out.rows("refunds")
    for month in _history_months(rows, "refund_datetime"):
        per_emp = Counter(r["employee_id"] for r in rows if r["refund_datetime"].startswith(month))
        assert max(per_emp.values()) < 10, month


def _shrink_by_store_month(out):
    acc = defaultdict(float)
    for r in out.rows("inventory_adjustments"):
        if r["adjustment_type"] == "Shrinkage":
            acc[(r["adjustment_datetime"][:7], r["store_id"])] += -float(r["adjustment_value"])
    return acc


def test_fnd002_ph005_shrink_concentrated_in_july(out):
    acc = _shrink_by_store_month(out)
    others = [acc[("2026-07", s)] for s in STORES if s != "PH-005"]
    assert acc[("2026-07", "PH-005")] >= 2.5 * (sum(others) / len(others))


def test_fnd002_no_shrink_outlier_in_history(out):
    acc = _shrink_by_store_month(out)
    for month in sorted({m for m, _ in acc if m < "2026-07"}):   # history + generated May-June counts
        values = {s: acc[(month, s)] for s in STORES}
        for s, v in values.items():
            rest = [x for t, x in values.items() if t != s]
            assert v < 1.5 * (sum(rest) / len(rest)), (month, s)


def test_fnd003_exactly_twelve_double_refunds(out):
    per_txn = Counter(r["original_transaction_id"] for r in out.rows("refunds"))
    assert sum(1 for n in per_txn.values() if n >= 2) == 12


def test_fnd004_ph002_manager_override_concentration(out):
    rows = [r for r in out.rows("discount_overrides") if within(r["override_datetime"], *LAST_30)]
    per = Counter(r["approving_manager_id"] for r in rows)
    peers = [n for e, n in per.items() if e != "EMP-0023"]
    assert per["EMP-0023"] >= 3 * (sum(peers) / len(peers))
    rows = out.rows("discount_overrides")
    for month in _history_months(rows, "override_datetime"):
        per_month = Counter(r["approving_manager_id"] for r in rows if r["override_datetime"].startswith(month))
        # 12 = the busiest NON-plant approver in the original window (EMP-0100, 10/month) + 20%;
        # EMP-0023 approves 38-54/month in the original window.
        assert max(per_month.values()) <= 12, month


def _reject_rates(out, start, end):
    total, rejected = Counter(), Counter()
    for c in out.rows("insurance_claims"):
        if within(c["submitted_datetime"], start, end):
            total[c["store_id"]] += 1
            rejected[c["store_id"]] += c["claim_status"] == "Rejected"
    return {s: rejected[s] / total[s] for s in STORES}


def test_fnd005_ph004_claim_rejection_above_chain(out):
    rates = _reject_rates(out, CORE_START, AS_OF)
    others = [rates[s] for s in STORES if s != "PH-004"]
    assert rates["PH-004"] >= 2 * (sum(others) / len(others))
    assert max(others) <= 0.08


def test_fnd005_no_rejection_outlier_in_history(out):
    month = date(2025, 8, 1)
    while month < CORE_START:
        nxt = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
        rates = _reject_rates(out, month, nxt - timedelta(days=1))
        assert max(rates.values()) <= 0.09, (month, rates)
        month = nxt


def test_fnd006_daniel_ross_repeated_shortages(out):
    short = Counter(r["employee_id"] for r in out.rows("cash_drawers")
                    if within(r["opened_at"], *LAST_90) and float(r["cash_variance"]) <= -10)
    assert short["EMP-0102"] >= 5
    assert all(n < 2 for e, n in short.items() if e != "EMP-0102")
    rows = out.rows("cash_drawers")
    for month in _history_months(rows, "opened_at"):
        monthly = Counter(r["employee_id"] for r in rows
                          if r["opened_at"].startswith(month) and float(r["cash_variance"]) <= -10)
        assert all(n < 2 for n in monthly.values()), month


def test_fnd007_reprint_before_own_refund(out):
    reprints = defaultdict(list)
    for r in out.rows("receipts"):
        if r["print_type"] == "Reprint":
            reprints[(r["transaction_id"], r["printed_by_employee_id"])].append(ts(r["printed_datetime"]))
    pairs = Counter()
    for f in out.rows("refunds"):
        when = ts(f["refund_datetime"])
        for printed in reprints[(f["original_transaction_id"], f["employee_id"])]:
            if timedelta(hours=1) <= when - printed <= timedelta(hours=48):
                pairs[f["employee_id"]] += 1
                break
    assert pairs["EMP-0006"] == 40
    assert all(n <= 2 for e, n in pairs.items() if e != "EMP-0006")


def _net_sales(out):
    acc = defaultdict(float)
    for t in out.rows("transactions"):
        acc[(t["store_id"], t["transaction_datetime"][:7])] += float(t["subtotal"]) - float(t["discount_amount"])
    return acc


def test_fnd008_ph004_july_sales_decline(out):
    acc = _net_sales(out)
    change = {s: acc[(s, "2026-07")] / acc[(s, "2026-06")] - 1 for s in STORES}
    assert change["PH-004"] <= -0.30
    assert all(abs(change[s]) <= 0.25 for s in STORES if s != "PH-004"), change  # original data swings up to +18%
