"""Fixed parameters of the pharmacy_demo generator. Changing any value changes the output."""
from datetime import date

SEED = 20260801

HISTORY_START = date(2025, 8, 1)   # first generated day (Friday)
CORE_START = date(2026, 5, 1)      # first day of the original Aug-2026 package (kept verbatim)
HISTORY_END = date(2026, 7, 31)    # last day with sales (inclusive, Friday)
AS_OF_EXCLUSIVE = date(2026, 8, 1) # query `to` = as_of (HISTORY_END, inclusive) + 1 day

PRICE_UPDATE_DATE = date(2026, 1, 1)
PRICE_UPDATE_FACTOR = 1.015        # chain-wide cost AND price/reimbursement list update

MARGIN_PLANT_STORE = "PH-003"
MARGIN_PLANT_START = date(2026, 7, 18)   # last 14 days of history
MARGIN_PLANT_COST_FACTOR = 1.08
MARGIN_PLANT_DRUG_COUNT = 5
HEAVY_DRUG_WEIGHT = 20             # popularity weight of the 5 heavy Rx drugs vs 1 for the rest

# Rows of the original receipts.csv left behind by DAAB write tests (2 UUID transactions + EMP-9999).
LEFTOVER_RECEIPT_IDS = frozenset({"RCT-0005317", "RCT-0005319", "RCT-0005328"})

PLANTED_PEOPLE = frozenset({"EMP-0006", "EMP-0023", "EMP-0102"})

# Mon..Sun multipliers. Mon-Thu = 1 so May-Jul top-ups only add Fri/Sat/Sun volume.
WEEKDAY_SHAPE = (1.0, 1.0, 1.0, 1.0, 1.06, 1.12, 1.05)
RX_WEEKDAY_SHAPE = (1.08, 1.05, 1.05, 1.05, 1.07, 0.80, 0.55)
MONTH_WEIGHT = {8: 0.97, 9: 0.95, 10: 0.98, 11: 1.03, 12: 1.15, 1: 1.06,
                2: 1.02, 3: 0.99, 4: 0.98, 5: 1.0, 6: 1.0, 7: 1.0}

RX_BASE_PER_STORE_DAY = 22
RX_COST_TO_REVENUE = 0.80          # acquisition cost / (payer + copay) for generated fills
RX_REJECT_RATE = 0.05
RX_REJECT_PLANT = {"PH-004": (date(2026, 5, 1), 0.155)}

TAX_RATE = 0.0825
NULL_CUSTOMER_SHARE = 0.22
LINE_DISCOUNT_SHARE = 0.17          # + overrides ~= 19.3% discounted lines in the original window
# Basket shape: lines-per-transaction is measured PER STORE from the original window (retail.lines_weights);
# line quantity mix measured on the original window (qty 1: 18998, 2: 1185, 3: 1204, 4: 1209 of 22596 lines):
LINE_QTY_WEIGHTS = (84, 5, 5, 6)                                                 # qty 1..4
OVERRIDE_PERCENTS = (25, 35, 45, 50)                                             # original discount_percent values
VOID_RATE = 0.024                  # history only
REFUND_RATE = 0.03                 # history only, refund dated before CORE_START
SHIFTS_PER_STORE_DAY = 2.2         # history only
SNAPSHOT_VARIANCE_SHARE = 0.18     # weekly count variances (calibrated to the non-plant July shrink level)
COUNT_VARIANCE_END = date(2026, 7, 1)   # no generated count variances in July 2026 (PH-005 shrink plant month)

WAGE_BY_ROLE = {
    "Cashier": 15.50, "Pharmacy Technician": 20.00, "Inventory Associate": 17.00,
    "Shift Supervisor": 21.00, "Assistant Manager": 26.00, "Store Manager": 34.00,
    "Pharmacist": 62.00,
}

FRONT_ROLES = ("Cashier", "Shift Supervisor", "Assistant Manager", "Store Manager")
MANAGER_ROLES = ("Store Manager", "Assistant Manager")
APPROVER_ROLES = ("Store Manager", "Assistant Manager", "Shift Supervisor")   # original override approvers
PAYMENT_METHODS = (("Credit Card", 44), ("Debit Card", 28), ("Cash", 20), ("Gift Card", 5), ("Split Payment", 3))
PAYERS = (("Care Network", 26), ("PayerOne", 26), ("United Mock", 25), ("HealthPlan TX", 23))
REJECTION_CODES = ("E31", "E22", "E14", "E01")
RX_STATUSES = (("Picked Up", 706), ("Ready", 89), ("Not Collected", 81), ("Reversed", 68), ("Cancelled", 56))
REFUND_METHODS = (("Gift Card", 40), ("Cash", 30), ("Original Payment", 30))
REFUND_REASONS = ("Product Defective", "Customer Changed Mind", "Incorrect Product", "Other")
VOID_REASONS = ("Duplicate scan", "Payment issue", "Price dispute", "Customer changed mind")
VOID_STAGES = ("Before Payment", "After Receipt Printed", "After Payment Authorization")
REGISTERS = ("REG-01", "REG-02", "REG-03", "REG-04", "REG-05", "REG-06")
