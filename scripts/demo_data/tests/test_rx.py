from collections import Counter
from datetime import date

import pytest

from conftest import BASE_DIR
from pharmacy_demo_gen import config as C
from pharmacy_demo_gen.catalog import prepare_catalog
from pharmacy_demo_gen.ctx import Ctx, price_factor
from pharmacy_demo_gen.rx import add_acquisition_cost, generate_prescriptions
from pharmacy_demo_gen.tables import load_base, parse_dt


@pytest.fixture(scope="module")
def staged():
    c = Ctx(load_base(BASE_DIR))
    prepare_catalog(c)
    original = {r["prescription_id"] for r in c.t["prescriptions"].rows}
    c.t["prescriptions"].columns.append("acquisition_cost")
    generate_prescriptions(c)
    add_acquisition_cost(c, original)
    return c, original


def test_every_store_day_has_rx_volume(staged):
    c, _ = staged
    per_day = Counter((r["store_id"], parse_dt(r["received_datetime"]).date()) for r in c.t["prescriptions"].rows)
    assert len(per_day) == 5 * 365
    assert min(per_day.values()) >= 8


def test_ph004_rejection_plant_only_from_may(staged):
    c, _ = staged
    total, rejected = Counter(), Counter()
    for claim in c.t["insurance_claims"].rows:
        key = (claim["store_id"], parse_dt(claim["submitted_datetime"]).date() >= C.CORE_START)
        total[key] += 1
        rejected[key] += claim["claim_status"] == "Rejected"
    assert 0.13 <= rejected[("PH-004", True)] / total[("PH-004", True)] <= 0.18
    assert rejected[("PH-004", False)] / total[("PH-004", False)] <= 0.07


def test_original_fill_cost_follows_paid_amount_and_plant(staged):
    c, original = staged
    for r in c.t["prescriptions"].rows:
        if r["prescription_id"] not in original:
            continue
        paid = float(r["insurance_payment"]) + float(r["customer_payment"])
        planted = r["store_id"] == "PH-003" and r["product_id"] in c.heavy_rx \
            and parse_dt(r["filled_datetime"]).date() >= date(2026, 7, 18)
        factor = 1.08 if planted else 1.0
        assert float(r["acquisition_cost"]) == pytest.approx(paid * 0.80 * factor, abs=0.011)


def test_generated_fill_cost_follows_paid_amount_like_originals(staged):
    c, original = staged
    generated = [r for r in c.t["prescriptions"].rows if r["prescription_id"] not in original]
    assert generated
    for r in generated[::37]:
        day = parse_dt(r["filled_datetime"]).date()
        factor = c.unit_cost(r["product_id"], r["store_id"], day) / (
            c.unit_cost_2026[r["product_id"]] * price_factor(day))
        paid = float(r["insurance_payment"]) + float(r["customer_payment"])
        assert float(r["acquisition_cost"]) == pytest.approx(paid * 0.80 * factor, abs=0.011)


def _margin(c, store, start, end):
    cost = paid = 0.0
    for r in c.t["prescriptions"].rows:
        if r["store_id"] != store or not start <= parse_dt(r["filled_datetime"]).date() <= end:
            continue
        cost += float(r["acquisition_cost"])
        paid += float(r["insurance_payment"]) + float(r["customer_payment"])
    return 1 - cost / paid


def test_each_store_overall_rx_margin_is_about_twenty_percent(staged):
    c, _ = staged
    for store in c.stores:
        assert 0.19 <= _margin(c, store, C.HISTORY_START, C.HISTORY_END) <= 0.21, store


def test_ph003_margin_drops_after_plant_others_flat(staged):
    c, _ = staged
    before, after = (date(2026, 6, 18), date(2026, 7, 17)), (date(2026, 7, 18), date(2026, 7, 31))
    for store in c.stores:
        delta = _margin(c, store, *before) - _margin(c, store, *after)
        if store == "PH-003":
            assert delta >= 0.02, delta
        else:
            assert abs(delta) <= 0.003, (store, delta)
