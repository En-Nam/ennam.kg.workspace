-- key: retail.refund_count
-- version: 1
-- grain: day
-- dims: [location_id, employee_id, approver_id]
-- unit: count
-- aggregation: additive
-- sample_size: refunds
-- requires: [refund]
-- Rules: RET-REF-005 (manager approval concentration: group_by approver_id).
SELECT location_id, employee_id, approver_id,
       CAST(refunded_at AS date) AS period_date,
       COUNT(*)                  AS value,
       COUNT(*)                  AS sample_size
FROM refund
WHERE refunded_at >= :from AND refunded_at < :to
GROUP BY 1, 2, 3, 4
