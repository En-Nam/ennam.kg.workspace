"""CSV tables as ordered column lists + list of string dicts; deterministic IO and ID sequences."""
import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from . import config as C

BASE_TABLES = (
    "stores", "products", "employees", "customers", "transactions", "transaction_items",
    "payments", "receipts", "invoices", "refunds", "refund_items", "voids",
    "discount_overrides", "cash_drawers", "employee_shifts", "inventory_movements",
    "inventory_adjustments", "inventory_snapshots", "prescriptions", "insurance_claims",
    "audit_events",
)
NEW_TABLES = ("vendors", "product_costs", "purchase_orders", "purchase_order_lines")


@dataclass
class Table:
    columns: list[str]
    rows: list[dict[str, str]] = field(default_factory=list)

    def add(self, row: dict) -> dict:
        unknown = set(row) - set(self.columns)
        if unknown:
            raise KeyError(f"unknown columns {sorted(unknown)}")
        clean = {c: fmt(row.get(c)) for c in self.columns}
        self.rows.append(clean)
        return clean


def fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def read_table(path: Path) -> Table:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = [dict(r) for r in reader]
        return Table(columns=list(reader.fieldnames or []), rows=rows)


def load_base(base_dir: Path) -> dict[str, Table]:
    """Original package minus the rows left behind by DAAB write tests (see config.LEFTOVER_RECEIPT_IDS)."""
    tables = {name: read_table(base_dir / f"{name}.csv") for name in BASE_TABLES}
    receipts = tables["receipts"]
    receipts.rows = [r for r in receipts.rows if r["receipt_id"] not in C.LEFTOVER_RECEIPT_IDS]
    return tables


def write_table(path: Path, table: Table) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=table.columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(table.rows)


class IdSeq:
    """Generated IDs live in a range that cannot collide with the original package (which starts at 1)."""

    def __init__(self, prefix: str, width: int, start: int):
        self.prefix, self.width, self.next_value = prefix, width, start

    def next(self) -> str:
        value = f"{self.prefix}{self.next_value:0{self.width}d}"
        self.next_value += 1
        return value


def parse_dt(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
