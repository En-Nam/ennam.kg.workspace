-- key: retail.manual_override_count
-- version: 1
-- grain: day
-- dims: [location_id, employee_id, approver_id]
-- unit: count
-- aggregation: additive
-- sample_size: overrides
-- requires: [price_override]
-- Rules: RET-DISC-003, RET-REF-005 (FND-004: group_by approver_id).
SELECT location_id, employee_id, approver_id,
       CAST(overridden_at AS date) AS period_date,
       COUNT(*)                    AS value,
       COUNT(*)                    AS sample_size
FROM price_override
WHERE overridden_at >= :from AND overridden_at < :to
GROUP BY 1, 2, 3, 4
