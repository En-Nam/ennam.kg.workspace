-- key: retail.no_sale_rate
SELECT drawer_id, closed_at, no_sale_count, expected_cash, counted_cash, _source_ref
FROM cash_drawer
WHERE closed_at >= :from AND closed_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
  AND (:dim_employee_id IS NULL OR COALESCE(employee_id, '') = :dim_employee_id)
ORDER BY closed_at, drawer_id
