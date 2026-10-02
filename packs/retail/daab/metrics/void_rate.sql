-- key: retail.void_rate
-- version: 1
-- grain: day
-- dims: [location_id, employee_id]
-- unit: percent
-- aggregation: ratio
-- sample_size: started sales
-- requires: [void, sale]
-- Rules: RET-VOID-001 "Voided Transactions ÷ Started Transactions × 100";
-- started = every sale row whatever its status.
WITH x AS (
  SELECT location_id, employee_id, CAST(voided_at AS date) AS period_date, 1 AS voids, 0 AS started
  FROM void
  WHERE voided_at >= :from AND voided_at < :to
  UNION ALL
  SELECT location_id, employee_id, CAST(sold_at AS date), 0, 1
  FROM sale
  WHERE sold_at >= :from AND sold_at < :to
)
SELECT location_id, employee_id, period_date,
       SUM(voids)   AS numerator,
       SUM(started) AS denominator,
       SUM(started) AS sample_size
FROM x
GROUP BY 1, 2, 3
