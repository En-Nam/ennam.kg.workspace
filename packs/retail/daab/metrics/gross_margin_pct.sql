-- key: retail.gross_margin_pct
-- version: 1
-- grain: day
-- dims: [location_id, category]
-- unit: percent
-- aggregation: ratio
-- sample_size: completed sales
-- requires: [sale, sale_line, product]
-- Rules: RET-MARGIN-001, RET-MARGIN-002. numerator = net sales − cost, denominator = net sales.
SELECT s.location_id,
       p.category,
       CAST(s.sold_at AS date) AS period_date,
       SUM(l.quantity * l.unit_price - COALESCE(l.discount_amount, 0)
           - l.quantity * COALESCE(l.unit_cost, p.unit_cost))          AS numerator,
       SUM(l.quantity * l.unit_price - COALESCE(l.discount_amount, 0)) AS denominator,
       COUNT(DISTINCT s.sale_id)                                       AS sample_size
FROM sale s
JOIN sale_line l   ON l.sale_id = s.sale_id
LEFT JOIN product p ON p.product_id = l.product_id
WHERE s.status = 'completed'
  AND NOT COALESCE(p.is_regulated, false)
  AND s.sold_at >= :from AND s.sold_at < :to
GROUP BY 1, 2, 3
