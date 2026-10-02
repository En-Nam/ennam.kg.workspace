-- key: retail.labor_cost
-- version: 1
-- grain: day
-- dims: [location_id]
-- unit: currency
-- aggregation: additive
-- sample_size: shifts with a wage rate
-- requires: [shift, labor_rate]
-- Rules: RET-LABOR-001 "Labor % = Total Labor Cost ÷ Net Sales × 100" (LAAM divides).
-- Beta: worked hours × the hourly rate effective on the shift date, no overtime premium.
WITH rate AS (
  SELECT employee_id, effective_from, hourly_rate,
         LEAD(effective_from) OVER (PARTITION BY employee_id ORDER BY effective_from) AS effective_to
  FROM labor_rate
)
SELECT s.location_id,
       CAST(s.start_at AS date) AS period_date,
       SUM((COALESCE(s.regular_hours, 0) + COALESCE(s.overtime_hours, 0)) * r.hourly_rate) AS value,
       COUNT(r.hourly_rate)     AS sample_size
FROM shift s
LEFT JOIN rate r
  ON r.employee_id = s.employee_id
 AND r.effective_from <= CAST(s.start_at AS date)
 AND (r.effective_to IS NULL OR CAST(s.start_at AS date) < r.effective_to)
WHERE s.start_at >= :from AND s.start_at < :to
GROUP BY 1, 2
