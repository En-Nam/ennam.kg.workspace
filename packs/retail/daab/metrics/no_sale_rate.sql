-- key: retail.no_sale_rate
-- version: 1
-- grain: day
-- dims: [location_id, employee_id]
-- unit: percent
-- aggregation: ratio
-- sample_size: drawer openings
-- requires: [cash_drawer, sale]
-- Rules: RET-CASH-004 (FND-006). numerator = no-sale drawer openings; denominator =
-- all drawer openings, approximated as no-sale openings + completed sales (the
-- source has no per-opening log).
WITH x AS (
  SELECT location_id, employee_id, CAST(closed_at AS date) AS period_date,
         COALESCE(no_sale_count, 0) AS no_sale, COALESCE(no_sale_count, 0) AS openings
  FROM cash_drawer
  WHERE closed_at >= :from AND closed_at < :to
  UNION ALL
  SELECT location_id, employee_id, CAST(sold_at AS date), 0, 1
  FROM sale
  WHERE status = 'completed' AND sold_at >= :from AND sold_at < :to
)
SELECT location_id, employee_id, period_date,
       SUM(no_sale)  AS numerator,
       SUM(openings) AS denominator,
       SUM(openings) AS sample_size
FROM x
GROUP BY 1, 2, 3
