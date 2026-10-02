-- key: retail.duplicate_refund_groups
-- Every refund of the repeated original sales (earlier ones included, any location),
-- so the reviewer sees each pair.
SELECT e.original_sale_id, e.refund_id, e.refunded_at, e.location_id, e.employee_id,
       e.amount, e.method, e._source_ref
FROM refund e
WHERE e.original_sale_id IN (
  SELECT r.original_sale_id FROM refund r
  WHERE r.refunded_at >= :from AND r.refunded_at < :to
    AND (:dim_location_id IS NULL OR COALESCE(r.location_id, '') = :dim_location_id)
    AND r.original_sale_id IS NOT NULL
    AND EXISTS (
      SELECT 1 FROM refund x
      WHERE x.original_sale_id = r.original_sale_id
        AND (x.refunded_at < r.refunded_at
             OR (x.refunded_at = r.refunded_at AND x.refund_id < r.refund_id))))
ORDER BY e.original_sale_id, e.refunded_at, e.refund_id
