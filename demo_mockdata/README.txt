MICHAEL PHARMACY CHAIN DEMO DATA PACKAGE
=========================================

Purpose
-------
This package provides a complete fictional multi-location pharmacy and front-store retail dataset
for demonstrating DAAB + LAAM + 4A.

Important
---------
- All names and data are fictional.
- Do not use this package for real patient, pharmacy, or compliance decisions.
- No real PHI is included.
- The dataset contains both pharmacy operations and CVS-style front-store retail receipts.

Package size
------------
Stores: 5
Employees: 110
Products: 800
Customers: 5000
Sales receipts: 5000
Receipt line items: 22596
Payments: 5000
Refunds: 232
Refund line items: 338
Voids: 120
Discount overrides: 311
Inventory snapshots: 1500
Inventory adjustments: 1308
Inventory movements: 22916
Prescriptions: 1500
Insurance claims: 1500
Employee shifts: 1000
Cash drawer sessions: 568
Audit events: 5220

Core relationship path
----------------------
Store -> Employee -> Shift -> Register -> Receipt -> Receipt Line Items -> Payment
      -> Refund/Void/Override -> Manager Approval -> Inventory Movement -> Audit Event

Most important files
--------------------
transactions.csv
transaction_items.csv
payments.csv
refunds.csv
refund_items.csv
discount_overrides.csv
inventory_snapshots.csv
inventory_adjustments.csv
prescriptions.csv
insurance_claims.csv
cash_drawers.csv
expected_findings.csv
demo_questions.txt

Intentional anomalies
---------------------
1. Sarah Miller at PH-001 has excessive refunds, including no-receipt and late-evening refunds.
2. PH-005 contains concentrated inventory shrinkage.
3. Twelve original receipts were intentionally refunded twice.
4. PH-002 has concentrated evening manager overrides.
5. PH-004 has an elevated insurance claim rejection rate.
6. Daniel Ross at PH-005 has repeated cash drawer shortages.
7. PH-004 has a July front-store sales decline.
8. Some products at PH-004 contain expired stock.

Recommended Friday demo flow
----------------------------
1. Ask: Which employee refunds the most?
2. Open Sarah Miller's refund summary.
3. Drill into the linked refund receipts and original sale line items.
4. Ask: Show duplicate refunds.
5. Ask: Which store has the highest inventory discrepancy?
6. Ask: Which store has the highest insurance claim rejection rate?
7. Ask: Which employee has repeated cash drawer shortages?
8. Ask LAAM to summarize the highest-risk operational issues and recommend follow-up actions.
