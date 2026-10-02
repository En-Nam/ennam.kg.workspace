-- key: retail.manual_override_count
SELECT override_id, overridden_at, sale_id, product_id, original_amount, adjusted_amount,
       discount_amount, _source_ref
FROM price_override
WHERE overridden_at >= :from AND overridden_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
  AND (:dim_employee_id IS NULL OR COALESCE(employee_id, '') = :dim_employee_id)
  AND (:dim_approver_id IS NULL OR COALESCE(approver_id, '') = :dim_approver_id)
ORDER BY overridden_at, override_id
