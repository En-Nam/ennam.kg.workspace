-- key: retail.cash_variance
-- version: 1
-- grain: day
-- dims: [location_id, employee_id]
-- unit: currency
-- aggregation: additive
-- sample_size: drawer closes
-- requires: [cash_drawer]
-- Rules: RET-CASH-001 "Cash Variance = Counted Cash − Expected Cash"; the ≤ −$25 and
-- "repeated shortage" thresholds stay in the LAAM rule (count_days over daily points).
SELECT location_id, employee_id,
       CAST(closed_at AS date)             AS period_date,
       SUM(counted_cash - expected_cash)   AS value,
       COUNT(*)                            AS sample_size
FROM cash_drawer
WHERE closed_at >= :from AND closed_at < :to
GROUP BY 1, 2, 3
