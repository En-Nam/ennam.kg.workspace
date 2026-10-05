-- key: retail.stockout_sku_count
SELECT s.snapshot_id, s.snapshot_date, s.product_id, s.book_qty, s.counted_qty, s._source_ref
FROM inventory_snapshot s
JOIN (
  SELECT i.location_id, i.product_id, i.snapshot_date, SUM(l.quantity) AS units_28d
  FROM inventory_snapshot i
  JOIN sale x      ON x.location_id = i.location_id AND x.status = 'completed'
                  AND x.sold_at >= i.snapshot_date - 28 AND x.sold_at < i.snapshot_date
  JOIN sale_line l ON l.sale_id = x.sale_id AND l.product_id = i.product_id
  WHERE i.snapshot_date >= :from AND i.snapshot_date < :to
  GROUP BY 1, 2, 3
) d ON d.location_id = s.location_id AND d.product_id = s.product_id AND d.snapshot_date = s.snapshot_date
WHERE s.snapshot_date >= :from AND s.snapshot_date < :to
  AND d.units_28d > 0
  AND COALESCE(s.counted_qty, s.book_qty) * 28.0 / d.units_28d <= 7
  AND (:dim_location_id IS NULL OR COALESCE(s.location_id, '') = :dim_location_id)
ORDER BY s.snapshot_date, s.product_id
