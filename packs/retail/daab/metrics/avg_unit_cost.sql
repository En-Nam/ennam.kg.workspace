-- key: retail.avg_unit_cost
-- version: 1
-- grain: day
-- dims: [location_id, product_id]
-- unit: currency
-- aggregation: ratio
-- sample_size: sale lines
-- requires: [sale, sale_line]
-- Rules: RET-VENDOR-001 "Cost Change % = (New Unit Cost − Previous Unit Cost) ÷ Previous" —
-- LAAM compares periods; numerator = Σ quantity × unit cost, denominator = Σ quantity.
SELECT s.location_id, l.product_id,
       CAST(s.sold_at AS date)            AS period_date,
       SUM(l.quantity * l.unit_cost)      AS numerator,
       SUM(l.quantity)                    AS denominator,
       COUNT(*)                           AS sample_size
FROM sale s
JOIN sale_line l ON l.sale_id = s.sale_id
WHERE s.status = 'completed'
  AND l.unit_cost IS NOT NULL
  AND s.sold_at >= :from AND s.sold_at < :to
GROUP BY 1, 2, 3
