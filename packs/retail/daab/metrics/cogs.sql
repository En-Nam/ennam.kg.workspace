-- key: retail.cogs
-- version: 1
-- grain: day
-- dims: [location_id, category]
-- unit: currency
-- aggregation: additive
-- sample_size: sale lines
-- requires: [sale, sale_line, product]
-- Rules: RET-MARGIN-002 (forecast input). Line cost, falling back to product cost.
SELECT s.location_id,
       p.category,
       CAST(s.sold_at AS date)                               AS period_date,
       SUM(l.quantity * COALESCE(l.unit_cost, p.unit_cost))  AS value,
       COUNT(*)                                              AS sample_size
FROM sale s
JOIN sale_line l   ON l.sale_id = s.sale_id
LEFT JOIN product p ON p.product_id = l.product_id
WHERE s.status = 'completed'
  AND NOT COALESCE(p.is_regulated, false)
  AND s.sold_at >= :from AND s.sold_at < :to
GROUP BY 1, 2, 3
