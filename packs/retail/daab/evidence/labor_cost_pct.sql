-- key: retail.labor_cost_pct
WITH rate AS (
  SELECT employee_id, effective_from, hourly_rate,
         LEAD(effective_from) OVER (PARTITION BY employee_id ORDER BY effective_from) AS effective_to
  FROM labor_rate
)
SELECT s.shift_id, s.employee_id, s.start_at, s.regular_hours, s.overtime_hours,
       r.hourly_rate, s._source_ref
FROM shift s
LEFT JOIN rate r
  ON r.employee_id = s.employee_id
 AND r.effective_from <= CAST(s.start_at AS date)
 AND (r.effective_to IS NULL OR CAST(s.start_at AS date) < r.effective_to)
WHERE s.start_at >= :from AND s.start_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(s.location_id, '') = :dim_location_id)
ORDER BY s.start_at, s.shift_id
