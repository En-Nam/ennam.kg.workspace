-- key: retail.labor_hours
-- version: 1
-- grain: day
-- dims: [location_id, employee_id]
-- unit: hours
-- aggregation: additive
-- sample_size: shifts
-- requires: [shift]
-- Rules: RET-LABOR-002/003 inputs, RET-LABOR-006. Worked hours = regular + overtime, dated by clock-in.
SELECT location_id, employee_id,
       CAST(start_at AS date)                                          AS period_date,
       SUM(COALESCE(regular_hours, 0) + COALESCE(overtime_hours, 0))   AS value,
       COUNT(*)                                                        AS sample_size
FROM shift
WHERE start_at >= :from AND start_at < :to
GROUP BY 1, 2, 3
