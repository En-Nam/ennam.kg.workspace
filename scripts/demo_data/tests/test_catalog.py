from collections import Counter
from datetime import date

import pytest

from conftest import BASE_DIR
from pharmacy_demo_gen import config as C
from pharmacy_demo_gen.catalog import build_product_costs, build_vendors, prepare_catalog
from pharmacy_demo_gen.ctx import Ctx
from pharmacy_demo_gen.staff import add_hourly_wage
from pharmacy_demo_gen.tables import load_base


@pytest.fixture(scope="module")
def ctx() -> Ctx:
    c = Ctx(load_base(BASE_DIR))
    prepare_catalog(c)
    return c


def test_rx_cost_is_per_dispensing_unit(ctx):
    assert len(ctx.rx_ids) == 74
    assert all(0 < ctx.unit_cost_2026[p] < 5 for p in ctx.rx_ids)
    for p in ctx.rx_ids:
        assert ctx.rx_revenue_per_unit[p] == pytest.approx(ctx.unit_cost_2026[p] / C.RX_COST_TO_REVENUE)


def test_plant_drugs_are_the_five_most_filled(ctx):
    fills = Counter(r["product_id"] for r in ctx.t["prescriptions"].rows)
    assert ctx.heavy_rx == sorted(ctx.rx_ids, key=lambda p: (-fills[p], p))[:5]


def test_unit_cost_timeline(ctx):
    drug = ctx.heavy_rx[0]
    now = ctx.unit_cost_2026[drug]
    assert ctx.unit_cost(drug, "PH-003", date(2026, 7, 17)) == pytest.approx(now)
    assert ctx.unit_cost(drug, "PH-003", date(2026, 7, 18)) == pytest.approx(now * 1.08)
    assert ctx.unit_cost(drug, "PH-001", date(2026, 7, 31)) == pytest.approx(now)
    assert ctx.unit_cost(drug, "PH-001", date(2025, 12, 31)) == pytest.approx(now / 1.015)


def test_vendors_and_cost_history(ctx):
    vendors = build_vendors(ctx)
    assert len(vendors.rows) == 35
    assert all(2 <= int(v["lead_time_days"]) <= 9 for v in vendors.rows)
    costs = build_product_costs(ctx)
    assert len(costs.rows) == 2 * 800 + 5
    assert [r["store_id"] for r in costs.rows if r["store_id"]] == ["PH-003"] * 5


def test_every_employee_gets_a_role_based_wage(ctx):
    add_hourly_wage(ctx)
    for e in ctx.t["employees"].rows:
        assert abs(float(e["hourly_wage"]) / C.WAGE_BY_ROLE[e["role"]] - 1) <= 0.051
