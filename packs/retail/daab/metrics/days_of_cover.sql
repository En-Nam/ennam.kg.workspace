-- key: retail.days_of_cover
-- version: 1
-- grain: day
-- dims: [location_id, product_id]
-- unit: days
-- aggregation: snapshot
-- sample_size: counted products
-- requires: [inventory_snapshot, sale, sale_line]
-- Rules: RET-INV-003 (stockout risk). On hand (counted, else book) ÷ average daily
-- units sold over the 28 days before the count. NULL when nothing sold (no cover
-- estimate), never a fake large number.
WITH s AS (
  SELECT location_id, product_id, snapshot_date, SUM(COALESCE(counted_qty, book_qty)) AS on_hand
  FROM inventory_snapshot
  WHERE snapshot_date >= :from AND snapshot_date < :to
  GROUP BY 1, 2, 3
),
d AS (
  SELECT s.location_id, s.product_id, s.snapshot_date, SUM(l.quantity) AS units_28d
  FROM s
  JOIN sale x      ON x.location_id = s.location_id AND x.status = 'completed'
                  AND x.sold_at >= s.snapshot_date - 28 AND x.sold_at < s.snapshot_date
  JOIN sale_line l ON l.sale_id = x.sale_id AND l.product_id = s.product_id
  GROUP BY 1, 2, 3
)
SELECT s.location_id, s.product_id, s.snapshot_date AS period_date,
       CASE WHEN d.units_28d > 0 THEN s.on_hand * 28.0 / d.units_28d END AS value,
       1 AS sample_size
FROM s
LEFT JOIN d ON d.location_id = s.location_id AND d.product_id = s.product_id AND d.snapshot_date = s.snapshot_date
