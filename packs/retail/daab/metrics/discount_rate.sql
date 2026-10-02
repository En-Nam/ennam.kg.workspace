-- key: retail.discount_rate
-- version: 1
-- grain: day
-- dims: [location_id, employee_id]
-- unit: percent
-- aggregation: ratio
-- sample_size: completed sales
-- requires: [sale, sale_line, product]
-- Rules: RET-DISC-002 (employee discount rate vs peers, ≥ 20 qualifying sales).
SELECT s.location_id, s.employee_id,
       CAST(s.sold_at AS date)                 AS period_date,
       SUM(COALESCE(l.discount_amount, 0))     AS numerator,
       SUM(l.quantity * l.unit_price)          AS denominator,
       COUNT(DISTINCT s.sale_id)               AS sample_size
FROM sale s
JOIN sale_line l   ON l.sale_id = s.sale_id
LEFT JOIN product p ON p.product_id = l.product_id
WHERE s.status = 'completed'
  AND NOT COALESCE(p.is_regulated, false)
  AND s.sold_at >= :from AND s.sold_at < :to
GROUP BY 1, 2, 3
