-- key: pharmacy.rx_cost
-- version: 1
-- grain: day
-- dims: [location_id, product_id]
-- unit: currency
-- aggregation: additive
-- sample_size: paid claims
-- requires: [claim, prescription]
-- lookback_days: 14
-- Rules: PH-MARGIN-001, forecast input. Acquisition cost = per-fill prescription cost.
SELECT c.location_id, p.product_id,
       CAST(c.submitted_at AS date) AS period_date,
       SUM(p.acquisition_cost)      AS value,
       COUNT(*)                     AS sample_size
FROM claim c
JOIN prescription p ON p.prescription_id = c.prescription_id
WHERE NOT c.is_rejected
  AND p.status NOT IN ('reversed', 'cancelled')
  AND c.submitted_at >= :from AND c.submitted_at < :to
GROUP BY 1, 2, 3
