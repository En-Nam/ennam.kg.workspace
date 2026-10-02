-- key: retail.refund_rate
SELECT refund_id, refunded_at, employee_id, approver_id, original_sale_id, amount, has_receipt, method, _source_ref
FROM refund
WHERE refunded_at >= :from AND refunded_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
  AND (:dim_employee_id IS NULL OR COALESCE(employee_id, '') = :dim_employee_id)
ORDER BY refunded_at, refund_id
