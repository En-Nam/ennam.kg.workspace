-- key: retail.gross_margin_pct
-- version: 1
-- grain: day
-- dims: [location_id, category]
-- unit: percent
-- aggregation: ratio
-- sample_size: completed sales with at least one costed line
-- requires: [sale, sale_line, product]
-- Rules: RET-MARGIN-001, RET-MARGIN-002. numerator = net sales − cost, denominator = net sales,
-- both over COSTED lines only (line cost, else product cost). A line with no cost at all is
-- excluded from numerator, denominator and sample_size, so unknown cost never lowers or raises
-- the margin; a group with no costed line yields NULL numerator and denominator (no value).
SELECT location_id,
       category,
       period_date,
       SUM(CASE WHEN cost_u IS NOT NULL THEN line_net - quantity * cost_u END) AS numerator,
       SUM(CASE WHEN cost_u IS NOT NULL THEN line_net END)                     AS denominator,
       COUNT(DISTINCT CASE WHEN cost_u IS NOT NULL THEN sale_id END)           AS sample_size
FROM (
  SELECT s.location_id,
         p.category,
         CAST(s.sold_at AS date)                                         AS period_date,
         s.sale_id,
         l.quantity,
         l.quantity * l.unit_price - COALESCE(l.discount_amount, 0)      AS line_net,
         COALESCE(l.unit_cost, p.unit_cost)                              AS cost_u
  FROM sale s
  JOIN sale_line l   ON l.sale_id = s.sale_id
  LEFT JOIN product p ON p.product_id = l.product_id
  WHERE s.status = 'completed'
    AND NOT COALESCE(p.is_regulated, false)
    AND s.sold_at >= :from AND s.sold_at < :to
) x
GROUP BY 1, 2, 3
