"""Stock simulation run BACKWARD from the original 2026-07-31 count, so the original snapshot stays the anchor.
Produces vendor receipts (RECEIPT movements + purchase orders), weekly Friday snapshots and count
adjustments before July 2026 (July keeps only the original count, which carries the PH-005 shrink plant).
The only generated adjustments allowed on/after 2026-07-01 are tiny "Stock correction" floor rows (type is neither
Shrinkage nor Expiration, so shrink/expiry measures ignore them); they keep on-hand >= 0 when the original
data has an unexplained inflow (return / positive count) with no earlier stock to cover it.
Rx stock is not simulated (prescriptions never produced movements in the original data)."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from . import config as C
from .ctx import Ctx
from .tables import Table, parse_dt

FLOOR_KIND = "Stock correction"  # tiny opening-stock write-offs that keep on-hand >= 0 (not shrink, not expiry)
PO_COLUMNS = ["po_id", "store_id", "vendor_id", "order_date", "expected_date", "received_datetime", "status"]
PO_LINE_COLUMNS = ["po_line_id", "po_id", "product_id", "quantity", "unit_cost"]


def _daily_deltas(ctx: Ctx) -> dict[tuple[str, str], dict[date, int]]:
    deltas: dict[tuple[str, str], dict[date, int]] = defaultdict(lambda: defaultdict(int))
    for m in ctx.t["inventory_movements"].rows:
        deltas[(m["store_id"], m["product_id"])][parse_dt(m["movement_datetime"]).date()] += int(m["quantity_change"])
    for a in ctx.t["inventory_adjustments"].rows:
        day = parse_dt(a["adjustment_datetime"]).date()
        deltas[(a["store_id"], a["product_id"])][day] += int(a["adjustment_quantity"])
    return deltas


def _snapshot_status(system: int, counted: int, value: float) -> str:
    if counted <= 0:
        return "Out of Stock"
    if counted == system:
        return "Matched"
    if abs(counted - system) >= 5 or abs(value) >= 100:
        return "Major Variance"
    return "Minor Variance"


def simulate_inventory(ctx: Ctx, vendors: Table) -> tuple[Table, Table]:
    deltas = _daily_deltas(ctx)
    anchors = {(s["store_id"], s["product_id"]): int(s["counted_quantity"]) for s in ctx.t["inventory_snapshots"].rows}
    snapshots, adjustments, receipts = [], [], []
    for store in ctx.stores:
        for pid in ctx.retail_ids:
            rp = int(ctx.products[pid]["reorder_point"])
            key = (store, pid)
            stock = anchors.get(key, rp * 2 + ctx.rng.randint(0, rp))
            day = C.HISTORY_END
            while day >= C.HISTORY_START:
                if key in anchors and day.weekday() == 4 and day < C.HISTORY_END:
                    stock = _weekly_count(ctx, key, day, stock, snapshots, adjustments)
                stock -= deltas[key].get(day, 0)
                if stock < 0:  # unexplained inflow (return/+count): book an earlier write-off so on-hand never < 0
                    adjustments.append((day, store, pid, -stock, stock, FLOOR_KIND))
                    stock = 0
                if stock > 4 * rp:
                    qty = stock - ctx.rng.randint(max(1, rp // 4), rp)
                    receipts.append((day, store, ctx.products[pid]["vendor_id"], pid, qty))
                    stock -= qty
                day -= timedelta(days=1)
    _emit_snapshots(ctx, snapshots)
    _emit_adjustments(ctx, adjustments)
    return _emit_receipts(ctx, vendors, receipts)


def _weekly_count(ctx: Ctx, key, day, stock, snapshots, adjustments) -> int:
    """`stock` is end-of-day book after the count; returns book before the count adjustment."""
    variance = 0
    if day < C.COUNT_VARIANCE_END and ctx.rng.random() < C.SNAPSHOT_VARIANCE_SHARE:
        variance = ctx.rng.choice([-2, -1, -1, 1])
        if stock - variance < 0:  # never count a negative book quantity
            variance = 0
    snapshots.append((day, key[0], key[1], stock - variance, stock))
    if variance:
        kind = "Shrinkage" if variance < 0 else "Cycle Count"
        adjustments.append((day, key[0], key[1], stock - variance, variance, kind))
    return stock - variance


def _emit_snapshots(ctx: Ctx, snapshots) -> None:
    for day, store, pid, system, counted in sorted(snapshots):
        value = round((counted - system) * ctx.unit_cost(pid, store, day), 2)
        ctx.t["inventory_snapshots"].add({
            "snapshot_id": ctx.ids["snp"].next(), "snapshot_date": day, "store_id": store, "product_id": pid,
            "system_quantity": system, "counted_quantity": counted, "variance_quantity": counted - system,
            "variance_value": value, "expired_quantity": 0, "status": _snapshot_status(system, counted, value)})


def _emit_adjustments(ctx: Ctx, adjustments) -> None:
    for day, store, pid, before, variance, kind in sorted(adjustments):
        counters = ctx.staff(store, ("Inventory Associate",), day) or ctx.staff(store, ("Store Manager",), day)
        ctx.t["inventory_adjustments"].add({
            "adjustment_id": ctx.ids["adj"].next(), "store_id": store, "product_id": pid,
            "employee_id": ctx.rng.choice(counters),
            "approving_manager_id": ctx.rng.choice(ctx.staff(store, C.MANAGER_ROLES, day)),
            "adjustment_datetime": datetime.combine(day, time(16)), "adjustment_type": kind,
            "quantity_before": before, "adjustment_quantity": variance, "quantity_after": before + variance,
            "adjustment_value": round(variance * ctx.unit_cost(pid, store, day), 2),
            "reason": "Opening-stock correction" if kind == FLOOR_KIND else kind,
            "reference_document": None, "flagged": False, "flag_reason": None})


def _emit_receipts(ctx: Ctx, vendors: Table, receipts) -> tuple[Table, Table]:
    lead = {v["vendor_id"]: int(v["lead_time_days"]) for v in vendors.rows}
    orders, lines = Table(PO_COLUMNS), Table(PO_LINE_COLUMNS)
    grouped = defaultdict(list)
    for day, store, vendor, pid, qty in receipts:
        grouped[(day, store, vendor)].append((pid, qty))
    for (day, store, vendor), items in sorted(grouped.items()):
        order_date = day - timedelta(days=lead[vendor] + ctx.rng.randint(0, 1))
        received = datetime.combine(day, time(9)) + timedelta(minutes=ctx.rng.randint(0, 120))
        receiver = ctx.staff(store, ("Inventory Associate",), day) or ctx.staff(store, ("Store Manager",), day)
        po_id = ctx.ids["po"].next()
        orders.add({"po_id": po_id, "store_id": store, "vendor_id": vendor, "order_date": order_date,
                    "expected_date": order_date + timedelta(days=lead[vendor]), "received_datetime": received,
                    "status": "Received"})
        employee = ctx.rng.choice(receiver)
        for pid, qty in sorted(items):
            lines.add({"po_line_id": ctx.ids["pol"].next(), "po_id": po_id, "product_id": pid, "quantity": qty,
                       "unit_cost": f"{ctx.unit_cost(pid, store, order_date):.4f}"})
            ctx.t["inventory_movements"].add({
                "movement_id": ctx.ids["mov"].next(), "store_id": store, "product_id": pid,
                "movement_datetime": received, "movement_type": "RECEIPT", "quantity_change": qty,
                "reference_id": po_id, "employee_id": employee})
    return orders, lines
