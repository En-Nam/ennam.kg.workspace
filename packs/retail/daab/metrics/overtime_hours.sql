-- key: retail.overtime_hours
-- version: 1
-- grain: day
-- dims: [location_id, employee_id]
-- unit: hours
-- aggregation: additive
-- sample_size: shifts
-- requires: [shift]
-- Rules: RET-LABOR-006 (overtime risk). Definition: the overtime hours the customer's
-- time system already recorded on each shift (shift.overtime_hours, i.e. hours beyond
-- the customer's own overtime rule) — NOT recomputed here against a threshold. The
-- request's projected-weekly-hours check is done by the LAAM rule.
SELECT location_id, employee_id,
       CAST(start_at AS date)            AS period_date,
       SUM(COALESCE(overtime_hours, 0))  AS value,
       COUNT(*)                          AS sample_size
FROM shift
WHERE start_at >= :from AND start_at < :to
GROUP BY 1, 2, 3
