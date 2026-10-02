-- key: retail.avg_unit_cost
SELECT s.sale_id, s.sold_at, l.quantity, l.unit_cost, l._source_ref
FROM sale s
JOIN sale_line l ON l.sale_id = s.sale_id
WHERE s.status = 'completed'
  AND l.unit_cost IS NOT NULL
  AND s.sold_at >= :from AND s.sold_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(s.location_id, '') = :dim_location_id)
  AND (:dim_product_id IS NULL OR COALESCE(l.product_id, '') = :dim_product_id)
ORDER BY s.sold_at, s.sale_id
