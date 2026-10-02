"""Product economics: Rx per-unit rebasing, vendors, dated cost history and the margin plant."""
import statistics
from collections import Counter, defaultdict
from datetime import timedelta

from . import config as C
from .ctx import Ctx
from .tables import Table

VENDOR_COLUMNS = ["vendor_id", "vendor_name", "lead_time_days", "order_weekday", "payment_terms", "status"]
PRODUCT_COST_COLUMNS = ["product_cost_id", "product_id", "store_id", "vendor_id",
                        "effective_from", "effective_to", "unit_cost", "change_reason"]
_NAME_A = ("Lone Star", "Gulf Coast", "Prairie", "Trinity", "Red River",
           "Brazos", "Pecos", "Panhandle", "Hill Country", "Big Bend")
_NAME_B = ("Medical Supply", "Wholesale", "Distributors", "Health Partners")


def rebase_rx_products(ctx: Ctx) -> None:
    """Original Rx unit_cost is per package while prescriptions.quantity is per unit (cost ~20x revenue).
    Rebase Rx unit_cost/retail_price to per-dispensing-unit values derived from the original fills."""
    claims = {r["prescription_id"]: r for r in ctx.t["insurance_claims"].rows}
    paid_per_unit, cash_per_unit = defaultdict(list), defaultdict(list)
    for rx in ctx.t["prescriptions"].rows:
        qty = int(rx["quantity"])
        claim = claims[rx["prescription_id"]]
        cash_per_unit[rx["product_id"]].append(float(rx["cash_price"]) / qty)
        if claim["claim_status"] == "Approved":
            paid = float(claim["approved_amount"]) + float(claim["customer_amount"])
            paid_per_unit[rx["product_id"]].append(paid / qty)
    all_paid = statistics.median(v for vs in paid_per_unit.values() for v in vs)
    all_cash = statistics.median(v for vs in cash_per_unit.values() for v in vs)
    for pid in ctx.rx_ids:
        row = ctx.products[pid]
        revenue_u = statistics.median(paid_per_unit[pid]) if paid_per_unit[pid] else all_paid
        cash_u = statistics.median(cash_per_unit[pid]) if cash_per_unit[pid] else all_cash
        cost_u = revenue_u * C.RX_COST_TO_REVENUE
        retail_u = max(cash_u, revenue_u * 1.2)
        row["unit_cost"] = f"{cost_u:.4f}"
        row["retail_price"] = f"{retail_u:.4f}"
        row["gross_margin_percent"] = f"{(retail_u - cost_u) / retail_u * 100:.1f}"


def prepare_catalog(ctx: Ctx) -> None:
    rebase_rx_products(ctx)
    ctx.unit_cost_2026 = {pid: float(r["unit_cost"]) for pid, r in ctx.products.items()}
    ctx.rx_revenue_per_unit = {pid: ctx.unit_cost_2026[pid] / C.RX_COST_TO_REVENUE for pid in ctx.rx_ids}
    fills = Counter(r["product_id"] for r in ctx.t["prescriptions"].rows)
    ranked = sorted(ctx.rx_ids, key=lambda p: (-fills[p], p))
    ctx.heavy_rx = ranked[:C.MARGIN_PLANT_DRUG_COUNT]
    for pid in ctx.heavy_rx:
        planted = ctx.unit_cost_2026[pid] * C.MARGIN_PLANT_COST_FACTOR
        ctx.store_cost_override[(pid, C.MARGIN_PLANT_STORE)] = (C.MARGIN_PLANT_START, planted)


def build_vendors(ctx: Ctx) -> Table:
    table = Table(VENDOR_COLUMNS)
    vendor_ids = sorted({r["vendor_id"] for r in ctx.products.values()})
    for i, vid in enumerate(vendor_ids):
        table.add({
            "vendor_id": vid,
            "vendor_name": f"{_NAME_A[i % len(_NAME_A)]} {_NAME_B[i // len(_NAME_A) % len(_NAME_B)]}",
            "lead_time_days": ctx.rng.randint(2, 9),
            "order_weekday": ctx.rng.randint(0, 4),
            "payment_terms": "Net 30",
            "status": "Active",
        })
    return table


def build_product_costs(ctx: Ctx) -> Table:
    table = Table(PRODUCT_COST_COLUMNS)
    before_update = C.PRICE_UPDATE_DATE - timedelta(days=1)
    for pid in sorted(ctx.products):
        vendor = ctx.products[pid]["vendor_id"]
        cost = ctx.unit_cost_2026[pid]
        table.add({"product_cost_id": ctx.ids["pc"].next(), "product_id": pid, "store_id": None,
                   "vendor_id": vendor, "effective_from": C.HISTORY_START, "effective_to": before_update,
                   "unit_cost": f"{cost / C.PRICE_UPDATE_FACTOR:.4f}", "change_reason": "Baseline price list"})
        table.add({"product_cost_id": ctx.ids["pc"].next(), "product_id": pid, "store_id": None,
                   "vendor_id": vendor, "effective_from": C.PRICE_UPDATE_DATE, "effective_to": None,
                   "unit_cost": f"{cost:.4f}", "change_reason": "Annual price list"})
    for (pid, store), (start, cost) in sorted(ctx.store_cost_override.items()):
        table.add({"product_cost_id": ctx.ids["pc"].next(), "product_id": pid, "store_id": store,
                   "vendor_id": ctx.products[pid]["vendor_id"], "effective_from": start, "effective_to": None,
                   "unit_cost": f"{cost:.4f}", "change_reason": "Vendor price increase"})
    return table
