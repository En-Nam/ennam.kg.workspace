-- key: retail.void_rate
SELECT void_id, voided_at, amount, post_tender, _source_ref
FROM void
WHERE voided_at >= :from AND voided_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
  AND (:dim_employee_id IS NULL OR COALESCE(employee_id, '') = :dim_employee_id)
ORDER BY voided_at, void_id
