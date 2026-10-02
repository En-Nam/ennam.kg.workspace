-- key: pharmacy.rx_margin_pct
-- version: 1
-- grain: day
-- dims: [location_id, product_id]
-- unit: percent
-- aggregation: ratio
-- sample_size: paid claims
-- requires: [claim, prescription]
-- lookback_days: 14
-- Rules: PH-MARGIN-001 (margin decline detection, breakdown by product_id).
-- numerator = Rx revenue − acquisition cost, denominator = Rx revenue.
SELECT c.location_id, p.product_id,
       CAST(c.submitted_at AS date) AS period_date,
       SUM(COALESCE(c.reimbursed_amount, 0) + COALESCE(c.patient_amount, 0) - p.acquisition_cost) AS numerator,
       SUM(COALESCE(c.reimbursed_amount, 0) + COALESCE(c.patient_amount, 0))                   AS denominator,
       COUNT(*)                     AS sample_size
FROM claim c
JOIN prescription p ON p.prescription_id = c.prescription_id
WHERE NOT c.is_rejected
  AND p.status NOT IN ('reversed', 'cancelled')
  AND c.submitted_at >= :from AND c.submitted_at < :to
GROUP BY 1, 2, 3
