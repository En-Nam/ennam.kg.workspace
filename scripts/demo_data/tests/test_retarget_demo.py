"""retarget_demo.py rebuilds the store targets (targets.xlsx -> DAAB dataset store_targets) for a shifted window.
Why it matters: RET-SALES-001 / RET-MARGIN-001 compare MONTH-TO-DATE actuals with a prorated monthly target, so a
date shift silently breaks FND-008 unless the target of the new as-of month is rebuilt: PH-004 must miss its target
by the original margin (ratio ~0.57) while every other store stays just above it (>= 1/0.98)."""
from datetime import date

import pytest

import retarget_demo as R
import shift_dates as S

STORES = ("PH-001", "PH-002", "PH-003", "PH-004", "PH-005")


def flat_daily(start: date, end: date, per_day: float = 1000.0, margin: float = 0.4, low: dict | None = None):
    """Synthetic daily sales: every store sells per_day (low[store] overrides) with the given margin."""
    out = {}
    d = start
    while d <= end:
        for s in STORES:
            net = (low or {}).get(s, per_day)
            out[(s, d)] = (net, net * (1 - margin))
        d = date.fromordinal(d.toordinal() + 1)
    return out


def ratio_of(daily, rows, store, as_of):
    """Exactly LAAM rules.ts: MTD actual / (monthly target * elapsedDays / daysInMonth)."""
    m = R.month_start(as_of)
    mtd = sum(v[0] for (s, d), v in daily.items() if s == store and m <= d <= as_of)
    target = next(r["Target Value"] for r in rows
                  if r["Store ID"] == store and r["Metric Key"] == "net_sales" and r["Period"].date() == m)
    return mtd / (target * as_of.day / R.days_in_month(m))


@pytest.fixture
def synthetic():
    daily = flat_daily(date(2025, 10, 3), date(2026, 10, 9))
    return daily, R.build_targets(daily, date(2026, 10, 9), plant_store="PH-004", plant_ratio=0.5666)


def test_as_of_month_plant_store_misses_by_the_plant_ratio(synthetic):
    daily, rows = synthetic
    assert ratio_of(daily, rows, "PH-004", date(2026, 10, 9)) == pytest.approx(0.5666, abs=0.005)


def test_as_of_month_other_stores_stay_just_above_target(synthetic):
    daily, rows = synthetic
    for s in ("PH-001", "PH-002", "PH-003", "PH-005"):
        assert 1 / R.ACHIEVED_FACTOR <= ratio_of(daily, rows, s, date(2026, 10, 9)) < 1.03, s


def test_one_row_per_store_metric_month_from_first_data_month_to_december(synthetic):
    _, rows = synthetic
    keys = [(r["Store ID"], r["Metric Key"], r["Period"].date()) for r in rows]
    assert len(keys) == len(set(keys))
    months = sorted({k[2] for k in keys})
    assert months[0] == date(2025, 10, 1) and months[-1] == date(2026, 12, 1) and len(months) == 15
    assert len(rows) == 15 * len(STORES) * 2


def test_past_months_are_achieved_by_every_store():
    """Past months use actual x 0.98 (as the generator did), so no store looks like it missed history."""
    daily = flat_daily(date(2025, 10, 3), date(2026, 10, 9), low={"PH-002": 700})
    rows = R.build_targets(daily, date(2026, 10, 9), plant_store="PH-004", plant_ratio=0.5666)
    for r in rows:
        if r["Metric Key"] == "net_sales" and date(2025, 11, 1) <= r["Period"].date() < date(2026, 10, 1):
            actual = sum(v[0] for (s, d), v in daily.items()
                         if s == r["Store ID"] and R.month_start(d) == r["Period"].date())
            assert actual / r["Target Value"] >= 1 / R.ACHIEVED_FACTOR, r


def test_future_months_follow_previous_year_times_growth(synthetic):
    daily, rows = synthetic
    nov = next(r for r in rows if r["Store ID"] == "PH-001" and r["Metric Key"] == "net_sales"
               and r["Period"].date() == date(2026, 11, 1))
    assert nov["Target Value"] == round(30 * 1000 * R.GROWTH_FACTOR, -2)


def test_margin_targets_sit_just_below_actual_so_margin_rule_stays_silent(synthetic):
    daily, rows = synthetic
    for r in rows:
        if r["Metric Key"] == "gross_margin_pct" and r["Period"].date() == date(2026, 10, 1):
            assert 40 - 2 < r["Target Value"] < 40, r   # RET-MARGIN-001 fires at value <= target - 2


def test_plant_ratio_is_read_from_the_original_package():
    # original July: PH-004 sold 31 * 500 against a July target of 30,000 -> 0.5167
    daily = flat_daily(date(2026, 7, 1), date(2026, 7, 31), low={"PH-004": 500})
    shifted = {(s, date.fromordinal(d.toordinal() + 70)): v for (s, d), v in daily.items()}
    targets = {("PH-004", "net_sales", date(2026, 7, 1)): 30000.0}
    got = R.plant_ratio_from_original(shifted, 70, targets, "PH-004", date(2026, 7, 31))
    assert got == pytest.approx(15500 / 30000)


# --- N for a wanted as-of -----------------------------------------------------------------------

@pytest.mark.parametrize("wanted, expected", [
    (date(2026, 10, 9), 70), (date(2026, 10, 8), 63), (date(2026, 10, 15), 70), (date(2026, 10, 16), 77),
    (date(2026, 7, 31), 0),
])
def test_weekly_shift_is_the_largest_multiple_of_7_not_past_the_wanted_as_of(wanted, expected):
    assert S.weekly_shift_days(date(2026, 7, 31), wanted) == expected


def test_weekly_shift_refuses_an_as_of_before_the_data_end():
    with pytest.raises(ValueError):
        S.weekly_shift_days(date(2026, 7, 31), date(2026, 7, 30))


# --- real package -------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def real70(tmp_path_factory):
    if not (S.DEFAULT_INPUT / "transactions.csv").exists():
        pytest.skip("demo_mockdata not present")
    out = tmp_path_factory.mktemp("s70") / "out"
    S.shift_directory(S.DEFAULT_INPUT, out, days=70, tables=S.LOAD_ORDER,
                      schema_sql="\n".join(p.read_text() for p in S.SCHEMA_FILES), dry_run=False)
    report = R.retarget(out, as_of=None, original_targets=S.DEFAULT_INPUT / "targets.xlsx")
    return out, report


def test_real_shift70_ratios_reproduce_fnd008_only(real70):
    _, report = real70
    assert report["as_of"] == "2026-10-09"
    ratios = report["as_of_month_ratios"]
    assert ratios["PH-004"] == pytest.approx(report["plant_ratio"], abs=0.005)
    assert 0.55 <= ratios["PH-004"] <= 0.60
    assert all(1.02 <= ratios[s] < 1.03 for s in ("PH-001", "PH-002", "PH-003", "PH-005")), ratios


def test_real_shift70_writes_targets_xlsx_next_to_the_csvs(real70):
    out, report = real70
    assert (out / "targets.xlsx").exists() and report["rows"] == 15 * 5 * 2


def test_days_for_cli_prints_n_for_the_real_package(capsys):
    """refresh_demo.sh reads N from this output; the original package ends Friday 2026-07-31."""
    if not (S.DEFAULT_INPUT / "transactions.csv").exists():
        pytest.skip("demo_mockdata not present")
    assert S.main(["--input", str(S.DEFAULT_INPUT), "--days-for", "2026-10-09"]) == 0
    assert capsys.readouterr().out.strip() == "70"
    assert S.main(["--input", str(S.DEFAULT_INPUT), "--days-for", "2026-07-01"]) == 1
