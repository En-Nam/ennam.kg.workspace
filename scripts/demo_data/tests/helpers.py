"""Shared helpers for the tests (dates are naive local time, windows are inclusive days)."""
from datetime import date, datetime

AS_OF = date(2026, 7, 31)
CORE_START = date(2026, 5, 1)
GENERATED_PREFIXES = ("TXN-1", "REF-1", "VOID-1", "OVR-1", "DRW-1", "SHF-1", "ADJ-1", "SNP-1", "RX-1", "CLM-1")
STORES = ("PH-001", "PH-002", "PH-003", "PH-004", "PH-005")


def ts(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")


def day_of(text: str) -> date:
    return date.fromisoformat(text[:10])


def within(text: str, start: date, end: date) -> bool:
    return start <= day_of(text) <= end


def is_generated(identifier: str) -> bool:
    return identifier.startswith(GENERATED_PREFIXES)


PRIMARY_KEYS = {
    "stores": "store_id", "products": "product_id", "employees": "employee_id", "customers": "customer_id",
    "transactions": "transaction_id", "transaction_items": "transaction_item_id", "payments": "payment_id",
    "receipts": "receipt_id", "invoices": "invoice_id", "refunds": "refund_id", "refund_items": "refund_item_id",
    "voids": "void_id", "discount_overrides": "override_id", "cash_drawers": "drawer_session_id",
    "employee_shifts": "shift_id", "inventory_movements": "movement_id", "inventory_adjustments": "adjustment_id",
    "inventory_snapshots": "snapshot_id", "prescriptions": "prescription_id", "insurance_claims": "claim_id",
    "audit_events": "audit_event_id", "vendors": "vendor_id", "product_costs": "product_cost_id",
    "purchase_orders": "po_id", "purchase_order_lines": "po_line_id",
}

FOREIGN_KEYS = [  # (table, column, referenced table) — mirrors pharmacy_demo FKs + extension.sql
    ("audit_events", "employee_id", "employees"), ("audit_events", "store_id", "stores"),
    ("cash_drawers", "employee_id", "employees"), ("cash_drawers", "store_id", "stores"),
    ("cash_drawers", "approving_manager_id", "employees"), ("customers", "preferred_store_id", "stores"),
    ("discount_overrides", "transaction_id", "transactions"), ("discount_overrides", "store_id", "stores"),
    ("discount_overrides", "product_id", "products"), ("discount_overrides", "approving_manager_id", "employees"),
    ("discount_overrides", "employee_id", "employees"), ("employee_shifts", "employee_id", "employees"),
    ("employee_shifts", "store_id", "stores"), ("employees", "store_id", "stores"),
    ("insurance_claims", "store_id", "stores"), ("insurance_claims", "prescription_id", "prescriptions"),
    ("inventory_adjustments", "product_id", "products"), ("inventory_adjustments", "employee_id", "employees"),
    ("inventory_adjustments", "store_id", "stores"), ("inventory_movements", "employee_id", "employees"),
    ("inventory_movements", "store_id", "stores"), ("inventory_movements", "product_id", "products"),
    ("inventory_snapshots", "product_id", "products"), ("inventory_snapshots", "store_id", "stores"),
    ("invoices", "transaction_id", "transactions"), ("invoices", "customer_id", "customers"),
    ("invoices", "store_id", "stores"), ("payments", "transaction_id", "transactions"),
    ("prescriptions", "pharmacist_employee_id", "employees"), ("prescriptions", "customer_id", "customers"),
    ("prescriptions", "store_id", "stores"), ("prescriptions", "technician_employee_id", "employees"),
    ("prescriptions", "product_id", "products"), ("receipts", "printed_by_employee_id", "employees"),
    ("receipts", "store_id", "stores"), ("receipts", "transaction_id", "transactions"),
    ("refund_items", "product_id", "products"), ("refund_items", "refund_id", "refunds"),
    ("refunds", "employee_id", "employees"), ("refunds", "customer_id", "customers"),
    ("refunds", "original_transaction_id", "transactions"), ("refunds", "store_id", "stores"),
    ("refunds", "approving_manager_id", "employees"), ("transaction_items", "product_id", "products"),
    ("transaction_items", "transaction_id", "transactions"), ("transactions", "customer_id", "customers"),
    ("transactions", "employee_id", "employees"), ("transactions", "store_id", "stores"),
    ("voids", "transaction_id", "transactions"), ("voids", "employee_id", "employees"),
    ("voids", "store_id", "stores"), ("products", "vendor_id", "vendors"),
    ("product_costs", "product_id", "products"), ("product_costs", "store_id", "stores"),
    ("product_costs", "vendor_id", "vendors"), ("purchase_orders", "store_id", "stores"),
    ("purchase_orders", "vendor_id", "vendors"), ("purchase_order_lines", "po_id", "purchase_orders"),
    ("purchase_order_lines", "product_id", "products"),
]
