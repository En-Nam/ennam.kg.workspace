"""Front-store sales: 9 months of history + weekend top-ups inside the original May-Jul window."""
from collections import Counter
from datetime import date, timedelta

from . import config as C
from .ctx import Ctx, days, price_factor
from .tables import parse_dt


def monthly_daily_base(ctx: Ctx) -> dict[tuple[str, int], float]:
    """Average original transactions per store per day for months 5, 6, 7 (keeps the PH-004 July dip)."""
    counts = Counter()
    for r in ctx.t["transactions"].rows:
        dt = parse_dt(r["transaction_datetime"])
        if C.CORE_START <= dt.date() <= C.HISTORY_END:
            counts[(r["store_id"], dt.month)] += 1
    month_days = {5: 31, 6: 30, 7: 31}
    return {(s, m): counts[(s, m)] / month_days[m] for s in ctx.stores for m in (5, 6, 7)}


def override_rates(ctx: Ctx) -> dict[str, float]:
    """Overrides per transaction in the original window, excluding planted approvers; 0 => chain mean."""
    txns = Counter(r["store_id"] for r in ctx.t["transactions"].rows)
    overrides = Counter(r["store_id"] for r in ctx.t["discount_overrides"].rows
                        if r["approving_manager_id"] not in C.PLANTED_PEOPLE)
    rates = {s: overrides[s] / txns[s] for s in ctx.stores}
    known = [v for v in rates.values() if v > 0]
    mean = sum(known) / len(known)
    return {s: v if v > 0 else mean for s, v in rates.items()}


def lines_weights(ctx: Ctx) -> dict[str, list[int]]:
    """Per store: how many original transactions had 1..12 lines (keeps each store's basket size)."""
    store_of = {t["transaction_id"]: t["store_id"] for t in ctx.t["transactions"].rows}
    lines = Counter(li["transaction_id"] for li in ctx.t["transaction_items"].rows)
    dist = {s: [0] * 12 for s in ctx.stores}
    for txn, n in lines.items():
        dist[store_of[txn]][min(n, 12) - 1] += 1
    return dist


def generate_sales(ctx: Ctx) -> list[dict]:
    ctx.override_rate = override_rates(ctx)
    ctx.lines_weights = lines_weights(ctx)
    base_sm = monthly_daily_base(ctx)
    base_store = {s: base_sm[(s, 5)] for s in ctx.stores}   # anchor history to the adjacent month (May 2026)
    generated = []
    for day in days(C.HISTORY_START, C.CORE_START - timedelta(days=1)):
        for store in ctx.stores:
            expected = base_store[store] * C.WEEKDAY_SHAPE[day.weekday()] * C.MONTH_WEIGHT[day.month]
            for _ in range(ctx.stoch_round(expected * ctx.rng.uniform(0.9, 1.1))):
                generated.append(make_transaction(ctx, store, day, history=True))
    for day in days(C.CORE_START, C.HISTORY_END):
        for store in ctx.stores:
            extra = base_sm[(store, day.month)] * (C.WEEKDAY_SHAPE[day.weekday()] - 1.0)
            for _ in range(ctx.stoch_round(extra)):
                generated.append(make_transaction(ctx, store, day, history=False))
    return generated


def make_transaction(ctx: Ctx, store: str, day: date, history: bool) -> dict:
    exclude = frozenset() if history else C.PLANTED_PEOPLE
    txn = {"transaction_id": ctx.ids["txn"].next(), "store_id": store, "day": day,
           "datetime": ctx.at(day, 8, 20), "register_id": ctx.rng.choice(C.REGISTERS),
           "cashier": ctx.rng.choice(ctx.staff(store, C.FRONT_ROLES, day, exclude)),
           "customer_id": ctx.customer(day)}
    sums = _add_lines(ctx, txn, history)
    total = round(sums["subtotal"] - sums["discount"] + sums["tax"], 2)
    method, receipt_number, dt = ctx.weighted(C.PAYMENT_METHODS), ctx.ids["rcp"].next(), txn["datetime"]
    ctx.t["transactions"].add({
        "transaction_id": txn["transaction_id"], "receipt_number": receipt_number, "store_id": store,
        "register_id": txn["register_id"], "employee_id": txn["cashier"], "customer_id": txn["customer_id"],
        "transaction_datetime": dt, "transaction_type": "Sale", "subtotal": round(sums["subtotal"], 2),
        "discount_amount": round(sums["discount"], 2), "tax_amount": round(sums["tax"], 2),
        "total_amount": total, "payment_method": method, "item_count": sums["units"],
        "prescription_included": False,
        "loyalty_used": txn["customer_id"] is not None and ctx.rng.random() < 0.5,
        "manager_override": sums["override"], "status": "Completed"})
    ctx.t["payments"].add({"payment_id": ctx.ids["pay"].next(), "transaction_id": txn["transaction_id"],
                           "payment_method": method, "amount": total, "payment_datetime": dt, "status": "Approved"})
    ctx.t["receipts"].add({"receipt_id": ctx.ids["rct"].next(), "transaction_id": txn["transaction_id"],
                           "receipt_number": receipt_number, "print_type": "Original",
                           "printed_datetime": dt + timedelta(seconds=60), "printed_by_employee_id": txn["cashier"],
                           "register_id": txn["register_id"], "store_id": store, "print_reason": None})
    if history and ctx.rng.random() < C.VOID_RATE:
        _add_void(ctx, txn, total)
    return txn


def _add_lines(ctx: Ctx, txn: dict, history: bool) -> dict:
    store, day, dt = txn["store_id"], txn["day"], txn["datetime"]
    n_lines = ctx.rng.choices(range(1, 13), weights=ctx.lines_weights[store])[0]
    wants_override = history and ctx.rng.random() < ctx.override_rate[store]
    override_line = ctx.rng.randrange(n_lines) if wants_override else None
    approver = ctx.rng.choice(ctx.staff(store, C.APPROVER_ROLES, day)) if wants_override else None
    sums = {"subtotal": 0.0, "discount": 0.0, "tax": 0.0, "units": 0, "override": override_line is not None}
    txn["lines"] = []
    for i in range(n_lines):
        pid = ctx.rng.choice(ctx.retail_ids)
        qty = ctx.rng.choices([1, 2, 3, 4], weights=C.LINE_QTY_WEIGHTS)[0]
        price = round(float(ctx.products[pid]["retail_price"]) * price_factor(day), 2)
        gross = round(qty * price, 2)
        if i == override_line:
            discount = _add_override(ctx, txn, pid, gross, approver)
        elif ctx.rng.random() < C.LINE_DISCOUNT_SHARE:
            discount = round(gross * ctx.rng.choice([0.05, 0.10, 0.20]), 2)
        else:
            discount = 0.0
        line_total = round(gross - discount, 2)
        tax = round(line_total * C.TAX_RATE, 2)
        ctx.t["transaction_items"].add({
            "transaction_item_id": ctx.ids["li"].next(), "transaction_id": txn["transaction_id"],
            "product_id": pid, "quantity": qty, "unit_price": price,
            "unit_cost": round(ctx.unit_cost(pid, store, day), 2), "discount_amount": discount,
            "tax_amount": tax, "line_total": line_total, "override_applied": i == override_line,
            "override_employee_id": approver if i == override_line else None,
            "department": ctx.products[pid]["category"]})
        ctx.t["inventory_movements"].add({
            "movement_id": ctx.ids["mov"].next(), "store_id": store, "product_id": pid, "movement_datetime": dt,
            "movement_type": "SALE", "quantity_change": -qty, "reference_id": txn["transaction_id"],
            "employee_id": txn["cashier"]})
        txn["lines"].append({"product_id": pid, "quantity": qty, "unit_price": price})
        sums["subtotal"] += gross
        sums["discount"] += discount
        sums["tax"] += tax
        sums["units"] += qty
    return sums


def _add_override(ctx: Ctx, txn: dict, pid: str, gross: float, approver: str) -> float:
    pct = ctx.rng.choice(C.OVERRIDE_PERCENTS)
    discount = round(gross * pct / 100, 2)
    ctx.t["discount_overrides"].add({
        "override_id": ctx.ids["ovr"].next(), "transaction_id": txn["transaction_id"],
        "store_id": txn["store_id"], "employee_id": txn["cashier"], "approving_manager_id": approver,
        "product_id": pid, "override_datetime": txn["datetime"], "original_amount": gross,
        "adjusted_amount": round(gross - discount, 2), "discount_amount": discount,
        "discount_percent": f"{pct:.1f}", "override_reason": "Manager price override",
        "approval_method": "Manager PIN", "flagged": pct > 40,
        "flag_reason": "Discount exceeds 40%" if pct > 40 else None})
    return discount


def _add_void(ctx: Ctx, txn: dict, total: float) -> None:
    void_dt = txn["datetime"] + timedelta(minutes=ctx.rng.randint(1, 30))
    amount = round(total * ctx.rng.uniform(0.2, 1.0), 2)
    late_high = void_dt.hour >= 20 and amount >= 100
    ctx.t["voids"].add({
        "void_id": ctx.ids["void"].next(), "transaction_id": txn["transaction_id"], "store_id": txn["store_id"],
        "register_id": txn["register_id"], "employee_id": txn["cashier"],
        "approving_manager_id": ctx.rng.choice(ctx.staff(txn["store_id"], C.MANAGER_ROLES, txn["day"])),
        "void_datetime": void_dt, "void_amount": amount, "void_reason": ctx.rng.choice(C.VOID_REASONS),
        "stage": ctx.rng.choice(C.VOID_STAGES), "flagged": late_high,
        "flag_reason": "Late high-value void" if late_high else None})
