"""12-month coverage, seasonality, and the rule that May-Jul additions never touch the planted signals."""
from collections import Counter, defaultdict
from datetime import date, timedelta

from helpers import AS_OF, CORE_START, STORES, day_of, is_generated

HISTORY_START = date(2025, 8, 1)
PLANTED = {"EMP-0006", "EMP-0023", "EMP-0102"}


def test_sales_cover_every_store_every_day_for_12_months(out):
    per_day = Counter((r["store_id"], day_of(r["transaction_datetime"])) for r in out.rows("transactions"))
    days = [HISTORY_START + timedelta(days=i) for i in range((AS_OF - HISTORY_START).days + 1)]
    missing = [(s, d) for s in STORES for d in days if per_day[(s, d)] == 0]
    assert not missing, missing[:5]
    assert max(day_of(r["transaction_datetime"]) for r in out.rows("transactions")) == AS_OF


def test_history_has_weekly_seasonality(out):
    by_weekday = defaultdict(list)
    per_day = Counter(day_of(r["transaction_datetime"]) for r in out.rows("transactions"))
    for d, n in per_day.items():
        if d < CORE_START:
            by_weekday[d.weekday()].append(n)
    mean = {k: sum(v) / len(v) for k, v in by_weekday.items()}
    assert mean[5] / mean[1] >= 1.08, "Saturday must be busier than Tuesday"


def test_history_has_december_peak(out):
    per_month = Counter(r["transaction_datetime"][:7] for r in out.rows("transactions"))
    assert per_month["2025-12"] > per_month["2025-11"] > per_month["2025-09"]


def test_no_generated_exceptions_inside_original_window(out):
    checks = [("refunds", "refund_id", "refund_datetime"), ("voids", "void_id", "void_datetime"),
              ("discount_overrides", "override_id", "override_datetime"),
              ("cash_drawers", "drawer_session_id", "opened_at"),
              ("employee_shifts", "shift_id", "scheduled_start")]
    for table, pk, col in checks:
        late = [r[pk] for r in out.rows(table) if is_generated(r[pk]) and day_of(r[col]) >= CORE_START]
        assert not late, f"{table}: {late[:3]}"
    # Count adjustments continue through May-June at the normal rate. From July on (PH-005 plant month) the only
    # generated adjustments allowed are the on-hand floor rows, typed exactly "Stock correction".
    july = [a for a in out.rows("inventory_adjustments")
            if is_generated(a["adjustment_id"]) and day_of(a["adjustment_datetime"]) >= date(2026, 7, 1)]
    assert all(a["adjustment_type"] == "Stock correction" for a in july), \
        [a["adjustment_id"] for a in july if a["adjustment_type"] != "Stock correction"][:3]


def test_planted_people_get_no_generated_sales_in_original_window(out):
    hits = [r["transaction_id"] for r in out.rows("transactions")
            if is_generated(r["transaction_id"]) and day_of(r["transaction_datetime"]) >= CORE_START
            and r["employee_id"] in PLANTED]
    assert not hits


def test_rx_volume_supports_store_level_rules(out):
    window = Counter(r["store_id"] for r in out.rows("prescriptions")
                     if date(2026, 7, 18) <= day_of(r["received_datetime"]) <= AS_OF)
    assert all(window[s] / 14 >= 15 for s in STORES), window


def test_vendor_receipts_and_weekly_snapshots_exist(out):
    kinds = Counter(r["movement_type"] for r in out.rows("inventory_movements"))
    assert kinds["RECEIPT"] > 1000
    assert {"SALE", "REFUND_RETURN", "RECEIPT"} == set(kinds)
    fridays = {r["snapshot_date"] for r in out.rows("inventory_snapshots")}
    assert len(fridays) == 53 and all(date.fromisoformat(d).weekday() == 4 for d in fridays)
    lead = {r["vendor_id"]: int(r["lead_time_days"]) for r in out.rows("vendors")}
    assert len(lead) == 35 and all(2 <= v <= 9 for v in lead.values())
