-- key: pharmacy.rx_revenue
-- version: 1
-- grain: day
-- dims: [location_id, product_id]
-- unit: currency
-- aggregation: additive
-- sample_size: paid claims
-- requires: [claim, prescription]
-- lookback_days: 14
-- Rules: PH-MARGIN-001, forecast input. Rx revenue = reimbursed (payer) + patient amount,
-- valid prescriptions only (status not reversed/cancelled), rejected claims excluded.
SELECT c.location_id, p.product_id,
       CAST(c.submitted_at AS date) AS period_date,
       SUM(COALESCE(c.reimbursed_amount, 0) + COALESCE(c.patient_amount, 0))                   AS value,
       COUNT(*)                     AS sample_size
FROM claim c
JOIN prescription p ON p.prescription_id = c.prescription_id
WHERE NOT c.is_rejected
  AND p.status NOT IN ('reversed', 'cancelled')
  AND c.submitted_at >= :from AND c.submitted_at < :to
GROUP BY 1, 2, 3
