"""History-only background operations: refunds, shifts and cash drawer sessions (normal rates, no plants)."""
from datetime import datetime, time, timedelta

from . import config as C
from .ctx import Ctx, days


def generate_refunds(ctx: Ctx, sales: list[dict]) -> None:
    """At most one refund per generated history sale, always dated before CORE_START."""
    for txn in sales:
        if txn["day"] >= C.CORE_START or ctx.rng.random() >= C.REFUND_RATE:
            continue
        refund_day = txn["day"] + timedelta(days=ctx.rng.randint(0, 30))
        if refund_day >= C.CORE_START:
            continue
        _add_refund(ctx, txn, refund_day)


def _add_refund(ctx: Ctx, txn: dict, refund_day) -> None:
    store = txn["store_id"]
    line = ctx.rng.choice(txn["lines"])
    qty = ctx.rng.randint(1, line["quantity"])
    amount = round(qty * line["unit_price"], 2)
    refund_dt = max(ctx.at(refund_day, 9, 20), txn["datetime"] + timedelta(hours=1))
    has_receipt = ctx.rng.random() < 0.85
    late, high = refund_dt.hour >= 20, amount >= 100
    reasons = [r for r, on in (("No receipt", not has_receipt), ("After 8 PM", late), ("High value", high)) if on]
    risk = 10 + 40 * (not has_receipt) + 20 * late + 20 * high
    returned = ctx.rng.random() < 0.85
    employee = ctx.rng.choice(ctx.staff(store, C.FRONT_ROLES, refund_day))
    refund_id = ctx.ids["ref"].next()
    ctx.t["refunds"].add({
        "refund_id": refund_id, "refund_transaction_id": ctx.ids["rtx"].next(),
        "original_transaction_id": txn["transaction_id"], "store_id": store, "register_id": txn["register_id"],
        "employee_id": employee, "approving_manager_id": ctx.rng.choice(ctx.staff(store, C.MANAGER_ROLES, refund_day)),
        "customer_id": txn["customer_id"], "refund_datetime": refund_dt, "refund_amount": amount,
        "refund_method": ctx.weighted(C.REFUND_METHODS),
        "refund_reason": "No Receipt" if not has_receipt else ctx.rng.choice(C.REFUND_REASONS),
        "original_receipt_present": has_receipt, "days_after_purchase": (refund_day - txn["day"]).days,
        "manager_override": high, "risk_score": risk, "flagged": risk >= 50,
        "flag_reason": "; ".join(reasons) if risk >= 50 else None})
    ctx.t["refund_items"].add({
        "refund_item_id": ctx.ids["rli"].next(), "refund_id": refund_id, "product_id": line["product_id"],
        "quantity": qty, "original_unit_price": line["unit_price"], "refunded_amount": amount,
        "returned_to_inventory": returned, "item_condition": "Resellable" if returned else "Damaged",
        "disposal_required": not returned})
    if returned:
        ctx.t["inventory_movements"].add({
            "movement_id": ctx.ids["mov"].next(), "store_id": store, "product_id": line["product_id"],
            "movement_datetime": refund_dt, "movement_type": "REFUND_RETURN", "quantity_change": qty,
            "reference_id": refund_id, "employee_id": employee})


def generate_shifts(ctx: Ctx) -> None:
    for day in days(C.HISTORY_START, C.CORE_START - timedelta(days=1)):
        for store in ctx.stores:
            managers = ctx.staff(store, ("Store Manager",), day)
            staff = ctx.staff(store, tuple(C.WAGE_BY_ROLE), day)
            for _ in range(ctx.stoch_round(C.SHIFTS_PER_STORE_DAY * ctx.rng.uniform(0.8, 1.2))):
                _add_shift(ctx, store, day, ctx.rng.choice(staff), managers[0])


def _add_shift(ctx: Ctx, store, day, employee, manager) -> None:
    start = datetime.combine(day, time(ctx.rng.choice([8, 10, 14])))
    end = start + timedelta(hours=8)
    late = ctx.rng.randint(1, 15) if ctx.rng.random() < 0.1 else 0
    early = ctx.rng.randint(0, 15)
    overtime = ctx.rng.choices([0.0, 0.25, 0.5], weights=[30, 50, 20])[0]
    clock_in = start + timedelta(minutes=late)
    clock_out = end - timedelta(minutes=early) + timedelta(hours=overtime)
    role = ctx.employees[employee]["role"]
    ctx.t["employee_shifts"].add({
        "shift_id": ctx.ids["shf"].next(), "employee_id": employee, "store_id": store,
        "scheduled_start": start, "scheduled_end": end, "actual_clock_in": clock_in, "actual_clock_out": clock_out,
        "regular_hours": "8", "overtime_hours": f"{overtime:.2f}", "late_minutes": late,
        "early_departure_minutes": early, "role_during_shift": role, "manager_on_duty": manager})
    if role in C.FRONT_ROLES:
        _add_drawer(ctx, store, day, employee, clock_in, clock_out)


def _add_drawer(ctx: Ctx, store, day, employee, opened, closed) -> None:
    sales = round(ctx.rng.uniform(600, 1500), 2)
    refunds = round(ctx.rng.uniform(0, 120), 2)
    expected = round(200.0 + sales - refunds, 2)
    variance = round(ctx.rng.gauss(0, 2.5), 2)
    ctx.t["cash_drawers"].add({
        "drawer_session_id": ctx.ids["drw"].next(), "store_id": store, "register_id": ctx.rng.choice(C.REGISTERS),
        "employee_id": employee, "opened_at": opened, "closed_at": closed, "opening_cash": "200.0",
        "expected_cash": expected, "counted_cash": round(expected + variance, 2), "cash_variance": variance,
        "no_sale_open_count": ctx.rng.choices([0, 1, 2, 3, 4], weights=[25, 35, 25, 10, 5])[0],
        "cash_refund_total": refunds, "cash_sales_total": sales,
        "approving_manager_id": ctx.rng.choice(ctx.staff(store, C.MANAGER_ROLES, day)),
        "flagged": False, "flag_reason": None})
