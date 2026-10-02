-- key: retail.no_receipt_refund_pct
-- version: 1
-- grain: day
-- dims: [location_id, employee_id]
-- unit: percent
-- aggregation: ratio
-- sample_size: refunds
-- requires: [refund]
-- Rules: RET-REF-002 "No-Receipt Refunds ÷ Total Refunds × 100". Unknown receipt flag is not counted as no-receipt.
SELECT location_id, employee_id,
       CAST(refunded_at AS date)                     AS period_date,
       COUNT(*) FILTER (WHERE has_receipt IS FALSE)  AS numerator,
       COUNT(*)                                      AS denominator,
       COUNT(*)                                      AS sample_size
FROM refund
WHERE refunded_at >= :from AND refunded_at < :to
GROUP BY 1, 2, 3
