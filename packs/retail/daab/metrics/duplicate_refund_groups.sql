-- key: retail.duplicate_refund_groups
-- version: 1
-- grain: day
-- dims: [location_id]
-- unit: count
-- aggregation: additive
-- sample_size: refunds examined
-- requires: [refund]
-- lookback_days: 30
-- Rules: RET-REF-004 (FND-003). value = refunds of an original sale that was already
-- refunded earlier (any date, any location), on the day/location of the repeat.
SELECT r.location_id,
       CAST(r.refunded_at AS date) AS period_date,
       SUM(CASE WHEN r.original_sale_id IS NOT NULL AND EXISTS (
             SELECT 1 FROM refund e
             WHERE e.original_sale_id = r.original_sale_id
               AND (e.refunded_at < r.refunded_at
                    OR (e.refunded_at = r.refunded_at AND e.refund_id < r.refund_id)))
           THEN 1 ELSE 0 END)  AS value,
       COUNT(*)                AS sample_size
FROM refund r
WHERE r.refunded_at >= :from AND r.refunded_at < :to
GROUP BY 1, 2
