-- key: retail.labor_cost_pct
-- version: 1
-- grain: day
-- dims: [location_id]
-- unit: percent
-- aggregation: ratio
-- sample_size: shifts with a wage rate
-- requires: [shift, labor_rate, sale]
-- Rules: RET-LABOR-001 "Labor % = Total Labor Cost ÷ Net Sales × 100". Labor cost as in
-- retail.labor_cost (no overtime premium); net sales = sale header net_amount. Days
-- without any priced shift have a NULL numerator (no value), never 0.
WITH rate AS (
  SELECT employee_id, effective_from, hourly_rate,
         LEAD(effective_from) OVER (PARTITION BY employee_id ORDER BY effective_from) AS effective_to
  FROM labor_rate
),
x AS (
  SELECT s.location_id, CAST(s.start_at AS date) AS period_date,
         (COALESCE(s.regular_hours, 0) + COALESCE(s.overtime_hours, 0)) * r.hourly_rate AS cost,
         CAST(0 AS numeric) AS sold,
         CASE WHEN r.hourly_rate IS NULL THEN 0 ELSE 1 END AS priced
  FROM shift s
  LEFT JOIN rate r
    ON r.employee_id = s.employee_id
   AND r.effective_from <= CAST(s.start_at AS date)
   AND (r.effective_to IS NULL OR CAST(s.start_at AS date) < r.effective_to)
  WHERE s.start_at >= :from AND s.start_at < :to
  UNION ALL
  SELECT location_id, CAST(sold_at AS date), CAST(NULL AS numeric), COALESCE(net_amount, 0), 0
  FROM sale
  WHERE status = 'completed' AND sold_at >= :from AND sold_at < :to
)
SELECT location_id, period_date,
       SUM(cost)   AS numerator,
       SUM(sold)   AS denominator,
       SUM(priced) AS sample_size
FROM x
GROUP BY 1, 2
