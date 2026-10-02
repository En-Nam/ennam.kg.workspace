-- key: retail.override_rate
-- version: 1
-- grain: day
-- dims: [location_id, employee_id]
-- unit: percent
-- aggregation: ratio
-- sample_size: sale lines
-- requires: [price_override, sale, sale_line]
-- Rules: RET-DISC-003 "Override rate materially exceeds peers". numerator = manual
-- overrides by the employee, denominator = sale lines the employee rang up. The
-- approving-manager view (FND-004, RET-REF-005) is retail.manual_override_count
-- grouped by approver_id.
WITH x AS (
  SELECT location_id, employee_id, CAST(overridden_at AS date) AS period_date, 1 AS overrides, 0 AS lines
  FROM price_override
  WHERE overridden_at >= :from AND overridden_at < :to
  UNION ALL
  SELECT s.location_id, s.employee_id, CAST(s.sold_at AS date), 0, 1
  FROM sale s
  JOIN sale_line l ON l.sale_id = s.sale_id
  WHERE s.status = 'completed' AND s.sold_at >= :from AND s.sold_at < :to
)
SELECT location_id, employee_id, period_date,
       SUM(overrides) AS numerator,
       SUM(lines)     AS denominator,
       SUM(lines)     AS sample_size
FROM x
GROUP BY 1, 2, 3
