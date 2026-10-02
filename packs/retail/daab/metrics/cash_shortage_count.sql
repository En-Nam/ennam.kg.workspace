-- key: retail.cash_shortage_count
-- version: 1
-- grain: day
-- dims: [location_id, employee_id]
-- unit: count
-- aggregation: additive
-- sample_size: drawer closes
-- requires: [cash_drawer]
-- Rules: RET-CASH-001 "Default shortage trigger: Cash Variance ≤ −$25" — counted per
-- drawer close (requested by Plan D so the rule counts shortages instead of summing
-- variances per day). The −25 is the request's default trigger.
SELECT location_id, employee_id,
       CAST(closed_at AS date)                                        AS period_date,
       COUNT(*) FILTER (WHERE counted_cash - expected_cash <= -25)    AS value,
       COUNT(*)                                                       AS sample_size
FROM cash_drawer
WHERE closed_at >= :from AND closed_at < :to
GROUP BY 1, 2, 3
