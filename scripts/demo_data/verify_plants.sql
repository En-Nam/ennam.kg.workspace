-- Post-load smoke check of pharmacy_demo (read-only). Expected values in the plan, Task 9.
-- Dates are the ORIGINAL window (ends 2026-07-31); after shift_dates.py run with -v shift_days=63
-- (psql ... -v shift_days=63 -f verify_plants.sql). Without it the shift is 0 = original behaviour.
\if :{?shift_days}
\else
\set shift_days 0
\endif
\pset footer off
SELECT 'window' AS check, min(transaction_datetime)::date AS first_day, max(transaction_datetime)::date AS last_day,
       count(*) FILTER (WHERE transaction_id !~ '^TXN-[0-9]{7}$') AS bad_ids
FROM transactions;

SELECT 'claim_rejection_may_jul' AS check, store_id,
       round(100.0 * avg((claim_status = 'Rejected')::int), 1) AS reject_pct
FROM insurance_claims WHERE submitted_datetime >= (DATE '2026-05-01' + :shift_days) AND submitted_datetime < (DATE '2026-08-01' + :shift_days)
GROUP BY store_id ORDER BY store_id;

SELECT 'rx_margin_pct' AS check, p.store_id,
       round(100 * (1 - sum(p.acquisition_cost) FILTER (WHERE p.received_datetime >= (DATE '2026-07-18' + :shift_days))
             / sum(c.approved_amount + c.customer_amount) FILTER (WHERE p.received_datetime >= (DATE '2026-07-18' + :shift_days))), 1) AS last_14d,
       round(100 * (1 - sum(p.acquisition_cost) FILTER (WHERE p.received_datetime < (DATE '2026-07-18' + :shift_days))
             / sum(c.approved_amount + c.customer_amount) FILTER (WHERE p.received_datetime < (DATE '2026-07-18' + :shift_days))), 1) AS prior_28d
FROM prescriptions p JOIN insurance_claims c USING (prescription_id)
WHERE c.claim_status = 'Approved' AND p.status NOT IN ('Reversed', 'Cancelled')
  AND p.received_datetime >= (DATE '2026-06-20' + :shift_days) AND p.received_datetime < (DATE '2026-08-01' + :shift_days)
GROUP BY p.store_id ORDER BY p.store_id;

SELECT 'sarah_refunds_jul' AS check, count(*) AS refunds FROM refunds
WHERE employee_id = 'EMP-0006' AND refund_datetime >= (DATE '2026-07-02' + :shift_days) AND refund_datetime < (DATE '2026-08-01' + :shift_days);

SELECT 'movement_types' AS check, movement_type, count(*) FROM inventory_movements GROUP BY 2 ORDER BY 2;
