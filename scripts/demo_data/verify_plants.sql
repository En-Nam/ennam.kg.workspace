-- Post-load smoke check of pharmacy_demo (read-only). Expected values in the plan, Task 9.
\pset footer off
SELECT 'window' AS check, min(transaction_datetime)::date AS first_day, max(transaction_datetime)::date AS last_day,
       count(*) FILTER (WHERE transaction_id !~ '^TXN-[0-9]{7}$') AS bad_ids
FROM transactions;

SELECT 'claim_rejection_may_jul' AS check, store_id,
       round(100.0 * avg((claim_status = 'Rejected')::int), 1) AS reject_pct
FROM insurance_claims WHERE submitted_datetime >= '2026-05-01' AND submitted_datetime < '2026-08-01'
GROUP BY store_id ORDER BY store_id;

SELECT 'rx_margin_pct' AS check, p.store_id,
       round(100 * (1 - sum(p.acquisition_cost) FILTER (WHERE p.received_datetime >= '2026-07-18')
             / sum(c.approved_amount + c.customer_amount) FILTER (WHERE p.received_datetime >= '2026-07-18')), 1) AS last_14d,
       round(100 * (1 - sum(p.acquisition_cost) FILTER (WHERE p.received_datetime < '2026-07-18')
             / sum(c.approved_amount + c.customer_amount) FILTER (WHERE p.received_datetime < '2026-07-18')), 1) AS prior_28d
FROM prescriptions p JOIN insurance_claims c USING (prescription_id)
WHERE c.claim_status = 'Approved' AND p.status NOT IN ('Reversed', 'Cancelled')
  AND p.received_datetime >= '2026-06-20' AND p.received_datetime < '2026-08-01'
GROUP BY p.store_id ORDER BY p.store_id;

SELECT 'sarah_refunds_jul' AS check, count(*) AS refunds FROM refunds
WHERE employee_id = 'EMP-0006' AND refund_datetime >= '2026-07-02' AND refund_datetime < '2026-08-01';

SELECT 'movement_types' AS check, movement_type, count(*) FROM inventory_movements GROUP BY 2 ORDER BY 2;
