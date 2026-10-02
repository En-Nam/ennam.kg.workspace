"""Prescriptions + insurance claims: full history, May-Jul volume top-up, acquisition_cost column."""
from collections import Counter
from datetime import timedelta

from . import config as C
from .ctx import Ctx, days, price_factor
from .tables import parse_dt


def generate_prescriptions(ctx: Ctx) -> None:
    existing = Counter((r["store_id"], parse_dt(r["received_datetime"]).date())
                       for r in ctx.t["prescriptions"].rows)
    weights = [C.HEAVY_DRUG_WEIGHT if p in ctx.heavy_rx else 1 for p in ctx.rx_ids]
    for day in days(C.HISTORY_START, C.HISTORY_END):
        for store in ctx.stores:
            target = C.RX_BASE_PER_STORE_DAY * C.RX_WEEKDAY_SHAPE[day.weekday()] * C.MONTH_WEIGHT[day.month]
            count = ctx.stoch_round(target * ctx.rng.uniform(0.9, 1.1))
            if day >= C.CORE_START:
                count = max(0, count - existing[(store, day)])
            for _ in range(count):
                pid = ctx.rng.choices(ctx.rx_ids, weights=weights)[0]
                _add_fill(ctx, store, day, pid)


def _reject_rate(store: str, day) -> float:
    plant = C.RX_REJECT_PLANT.get(store)
    if plant and day >= plant[0]:
        return plant[1]
    return C.RX_REJECT_RATE


def _add_fill(ctx: Ctx, store: str, day, pid: str) -> None:
    received = ctx.at(day, 8, 19)
    turnaround = ctx.rng.randint(10, 60)
    filled = received + timedelta(minutes=turnaround)
    qty = ctx.rng.choice((30, 30, 30, 30, 60, 90))
    pf = price_factor(day)
    paid = round(qty * ctx.rx_revenue_per_unit[pid] * pf * ctx.rng.uniform(0.98, 1.02), 2)
    copay = round(paid * ctx.rng.uniform(0.05, 0.15), 2)
    cash_price = round(qty * float(ctx.products[pid]["retail_price"]) * pf, 2)
    rejected = ctx.rng.random() < _reject_rate(store, day)
    approved = 0.0 if rejected else round(paid - copay, 2)
    status = ctx.weighted(C.RX_STATUSES)
    rx_id = ctx.ids["rx"].next()
    ctx.t["prescriptions"].add({
        "prescription_id": rx_id, "prescription_number": ctx.ids["rxn"].next(), "store_id": store,
        "pharmacist_employee_id": ctx.rng.choice(ctx.staff(store, ("Pharmacist",), day)),
        "technician_employee_id": ctx.rng.choice(ctx.staff(store, ("Pharmacy Technician",), day)),
        "customer_id": ctx.customer(day, allow_none=False), "product_id": pid,
        "received_datetime": received, "filled_datetime": filled,
        "picked_up_datetime": filled + timedelta(hours=ctx.rng.randint(2, 48)) if status == "Picked Up" else None,
        "quantity": qty, "refill_number": ctx.rng.randint(0, 5), "cash_price": cash_price,
        "customer_payment": copay, "insurance_payment": approved, "status": status,
        "turnaround_minutes": turnaround, "reversal_flag": status == "Reversed", "exception_reason": None,
        "acquisition_cost": None})
    ctx.t["insurance_claims"].add({
        "claim_id": ctx.ids["clm"].next(), "prescription_id": rx_id, "store_id": store,
        "payer_name": ctx.weighted(C.PAYERS), "submitted_datetime": received, "claim_amount": cash_price,
        "approved_amount": approved, "customer_amount": copay,
        "claim_status": "Rejected" if rejected else "Approved",
        "rejection_code": ctx.rng.choice(C.REJECTION_CODES) if rejected else None,
        "resubmission_count": ctx.rng.randint(0, 2) if rejected else 0,
        "resolved_datetime": received + timedelta(minutes=ctx.rng.randint(5, 60))})


def add_acquisition_cost(ctx: Ctx, original_ids: set[str]) -> None:
    """New column. Generated fills: quantity x unit cost effective at fill date + store.
    Original fills: their quantity is unrelated to their price, so cost = paid amount x RX_COST_TO_REVENUE,
    scaled by the same dated store cost factor (keeps the margin plant visible and low-noise)."""
    for row in ctx.t["prescriptions"].rows:
        fill_day = parse_dt(row["filled_datetime"] or row["received_datetime"]).date()
        unit_cost = ctx.unit_cost(row["product_id"], row["store_id"], fill_day)
        if row["prescription_id"] in original_ids:
            factor = unit_cost / (ctx.unit_cost_2026[row["product_id"]] * price_factor(fill_day))
            paid = float(row["insurance_payment"]) + float(row["customer_payment"])
            cost = paid * C.RX_COST_TO_REVENUE * factor
        else:
            cost = int(row["quantity"]) * unit_cost
        row["acquisition_cost"] = f"{cost:.2f}"
