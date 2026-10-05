-- key: retail.stockout_sku_count
-- version: 1
-- grain: day
-- dims: [location_id]
-- unit: count
-- aggregation: snapshot
-- sample_size: counted products
-- requires: [inventory_snapshot, sale, sale_line]
-- Rules: RET-INV-003 (stockout risk, one finding per location). Number of products that sell
-- (units sold in the 28 days before the count > 0) and have at most 7 days of cover. Cover = on hand
-- (counted, else book) ÷ average daily units sold; on hand <= 0 is out of stock (0 days). Products
-- nothing sold of are not counted: there is no demand to run out for.
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
SELECT s.location_id, s.snapshot_date AS period_date,
       SUM(CASE WHEN d.units_28d > 0 AND s.on_hand * 28.0 / d.units_28d <= 7 THEN 1 ELSE 0 END) AS value,
       COUNT(*) AS sample_size
FROM s
LEFT JOIN d ON d.location_id = s.location_id AND d.product_id = s.product_id AND d.snapshot_date = s.snapshot_date
GROUP BY 1, 2
