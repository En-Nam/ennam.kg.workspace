-- key: retail.reprint_before_refund_count
-- version: 1
-- grain: day
-- dims: [location_id, employee_id]
-- unit: count
-- aggregation: additive
-- sample_size: refunds
-- requires: [refund, receipt_print]
-- Rules: RET-X-REPRINT-001 (FND-007): value = refunds whose original sale receipt the
-- same employee reprinted 1–48 hours before refunding it; sample_size = all refunds.
SELECT r.location_id, r.employee_id,
       CAST(r.refunded_at AS date) AS period_date,
       SUM(CASE WHEN EXISTS (
             SELECT 1 FROM receipt_print p
             WHERE p.sale_id = r.original_sale_id
               AND p.print_type = 'reprint'
               AND p.employee_id = r.employee_id
               AND p.printed_at >= r.refunded_at - INTERVAL '48 hours'
               AND p.printed_at <= r.refunded_at - INTERVAL '1 hour')
           THEN 1 ELSE 0 END)  AS value,
       COUNT(*)                AS sample_size
FROM refund r
WHERE r.refunded_at >= :from AND r.refunded_at < :to
GROUP BY 1, 2, 3
