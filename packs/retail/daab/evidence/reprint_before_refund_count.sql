-- key: retail.reprint_before_refund_count
-- One row per (refund, matching reprint) pair.
SELECT r.refund_id, r.refunded_at, r.original_sale_id, r.amount,
       p.receipt_id, p.printed_at, r._source_ref
FROM refund r
JOIN receipt_print p
  ON p.sale_id = r.original_sale_id
 AND p.print_type = 'reprint'
 AND p.employee_id = r.employee_id
 AND p.printed_at >= r.refunded_at - INTERVAL '48 hours'
 AND p.printed_at <= r.refunded_at - INTERVAL '1 hour'
WHERE r.refunded_at >= :from AND r.refunded_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(r.location_id, '') = :dim_location_id)
  AND (:dim_employee_id IS NULL OR COALESCE(r.employee_id, '') = :dim_employee_id)
ORDER BY r.refunded_at, r.refund_id, p.printed_at
