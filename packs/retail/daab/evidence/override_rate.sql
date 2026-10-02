-- key: retail.override_rate
SELECT override_id, overridden_at, sale_id, product_id, approver_id, original_amount,
       adjusted_amount, discount_amount, _source_ref
FROM price_override
WHERE overridden_at >= :from AND overridden_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
  AND (:dim_employee_id IS NULL OR COALESCE(employee_id, '') = :dim_employee_id)
ORDER BY overridden_at, override_id
