-- key: retail.inventory_variance_value
SELECT i.snapshot_id, i.snapshot_date, i.book_qty, i.counted_qty, i.expired_qty, p.unit_cost, i._source_ref
FROM inventory_snapshot i
LEFT JOIN product p ON p.product_id = i.product_id
WHERE i.snapshot_date >= :from AND i.snapshot_date < :to
  AND (:dim_location_id IS NULL OR COALESCE(i.location_id, '') = :dim_location_id)
  AND (:dim_product_id IS NULL OR COALESCE(i.product_id, '') = :dim_product_id)
ORDER BY i.snapshot_date, i.snapshot_id
