"""Shared generation context: one seeded RNG, the tables, lookups and ID sequences."""
import bisect
import random
from datetime import date, datetime, time, timedelta

from . import config as C
from .tables import IdSeq, Table


def days(start: date, end: date):
    """Inclusive day range."""
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def price_factor(day: date) -> float:
    """Cost/price/reimbursement list level relative to the 2026 list."""
    return 1.0 if day >= C.PRICE_UPDATE_DATE else 1.0 / C.PRICE_UPDATE_FACTOR


class Ctx:
    def __init__(self, tables: dict[str, Table], seed: int = C.SEED):
        self.rng = random.Random(seed)
        self.t = tables
        self.products = {r["product_id"]: r for r in tables["products"].rows}
        self.rx_ids = sorted(p for p, r in self.products.items() if r["prescription_required"] == "True")
        self.retail_ids = sorted(p for p, r in self.products.items() if r["prescription_required"] != "True")
        self.employees = {r["employee_id"]: r for r in tables["employees"].rows}
        self.stores = sorted(r["store_id"] for r in tables["stores"].rows)
        signups = sorted((r["signup_date"], r["customer_id"]) for r in tables["customers"].rows)
        self._signup_dates = [s for s, _ in signups]
        self._signup_ids = [c for _, c in signups]
        self.ids = {
            "txn": IdSeq("TXN-", 7, 1_000_001), "rcp": IdSeq("RCP-", 8, 10_000_001),
            "li": IdSeq("LI-", 8, 10_000_001), "pay": IdSeq("PAY-", 8, 10_000_001),
            "rct": IdSeq("RCT-", 7, 1_000_001), "mov": IdSeq("MOV-", 8, 10_000_001),
            "ref": IdSeq("REF-", 6, 100_001), "rtx": IdSeq("RTX-", 6, 100_001),
            "rli": IdSeq("RLI-", 7, 1_000_001), "void": IdSeq("VOID-", 6, 100_001),
            "ovr": IdSeq("OVR-", 6, 100_001), "drw": IdSeq("DRW-", 7, 1_000_001),
            "shf": IdSeq("SHF-", 7, 1_000_001), "adj": IdSeq("ADJ-", 7, 1_000_001),
            "snp": IdSeq("SNP-", 8, 10_000_001), "rx": IdSeq("RX-", 7, 1_000_001),
            "rxn": IdSeq("RXN-", 7, 2_000_001), "clm": IdSeq("CLM-", 7, 1_000_001),
            "pc": IdSeq("PC-", 6, 1), "po": IdSeq("PO-", 6, 1), "pol": IdSeq("POL-", 7, 1),
        }
        self.unit_cost_2026: dict[str, float] = {}      # filled by catalog.prepare_catalog
        self.rx_revenue_per_unit: dict[str, float] = {}  # filled by catalog.prepare_catalog
        self.store_cost_override: dict[tuple[str, str], tuple[date, float]] = {}
        self.heavy_rx: list[str] = []
        self.override_rate: dict[str, float] = {}  # filled by retail.generate_sales
        self.lines_weights: dict[str, list[int]] = {}  # filled by retail.generate_sales

    # ---------- randomness helpers ----------
    def stoch_round(self, x: float) -> int:
        base = int(x)
        return base + (1 if self.rng.random() < x - base else 0)

    def weighted(self, pairs) -> str:
        values = [v for v, _ in pairs]
        weights = [w for _, w in pairs]
        return self.rng.choices(values, weights=weights, k=1)[0]

    def at(self, day: date, hour_from: int, hour_to: int) -> datetime:
        """Random timestamp on `day` with hour in [hour_from, hour_to]."""
        secs = self.rng.randint(hour_from * 3600, hour_to * 3600 + 3599)
        return datetime.combine(day, time()) + timedelta(seconds=secs)

    # ---------- lookups ----------
    def staff(self, store: str, roles, day: date, exclude=frozenset()) -> list[str]:
        out = [e for e, r in self.employees.items()
               if r["store_id"] == store and r["role"] in roles and r["hire_date"] <= day.isoformat()
               and e not in exclude]
        return sorted(out)

    def customer(self, day: date, allow_none: bool = True) -> str | None:
        if allow_none and self.rng.random() < C.NULL_CUSTOMER_SHARE:
            return None
        hi = bisect.bisect_right(self._signup_dates, day.isoformat())
        if hi == 0:
            return None
        return self._signup_ids[self.rng.randrange(hi)]

    def unit_cost(self, product_id: str, store: str, day: date) -> float:
        override = self.store_cost_override.get((product_id, store))
        if override and day >= override[0]:
            return override[1]
        return self.unit_cost_2026[product_id] * price_factor(day)
