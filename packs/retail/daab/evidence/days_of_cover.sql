-- key: retail.days_of_cover
SELECT snapshot_id, snapshot_date, book_qty, counted_qty, expired_qty, _source_ref
FROM inventory_snapshot
WHERE snapshot_date >= :from AND snapshot_date < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
  AND (:dim_product_id IS NULL OR COALESCE(product_id, '') = :dim_product_id)
ORDER BY snapshot_date, snapshot_id
