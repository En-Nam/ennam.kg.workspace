-- key: retail.avg_ticket
-- version: 1
-- grain: day
-- dims: [location_id]
-- unit: currency
-- aggregation: ratio
-- sample_size: completed sales
-- requires: [sale, sale_line, product]
-- Rules: RET-SALES-001 (average-ticket change). numerator = net sales, denominator = sales.
SELECT s.location_id,
       CAST(s.sold_at AS date)                                         AS period_date,
       SUM(l.quantity * l.unit_price - COALESCE(l.discount_amount, 0)) AS numerator,
       COUNT(DISTINCT s.sale_id)                                       AS denominator,
       COUNT(DISTINCT s.sale_id)                                       AS sample_size
FROM sale s
JOIN sale_line l   ON l.sale_id = s.sale_id
LEFT JOIN product p ON p.product_id = l.product_id
WHERE s.status = 'completed'
  AND NOT COALESCE(p.is_regulated, false)
  AND s.sold_at >= :from AND s.sold_at < :to
GROUP BY 1, 2
