-- key: retail.net_sales
SELECT s.sale_id, s.sold_at, s.employee_id, l.product_id, p.category,
       l.quantity, l.unit_price, l.unit_cost, l.discount_amount, l._source_ref
FROM sale s
JOIN sale_line l   ON l.sale_id = s.sale_id
LEFT JOIN product p ON p.product_id = l.product_id
WHERE s.status = 'completed'
  AND NOT COALESCE(p.is_regulated, false)
  AND s.sold_at >= :from AND s.sold_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(s.location_id, '') = :dim_location_id)
  AND (:dim_category IS NULL OR COALESCE(p.category, '') = :dim_category)
ORDER BY s.sold_at, s.sale_id, l.sale_line_id
