-- key: retail.labor_hours
SELECT shift_id, start_at, end_at, regular_hours, overtime_hours, _source_ref
FROM shift
WHERE start_at >= :from AND start_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
  AND (:dim_employee_id IS NULL OR COALESCE(employee_id, '') = :dim_employee_id)
ORDER BY start_at, shift_id
