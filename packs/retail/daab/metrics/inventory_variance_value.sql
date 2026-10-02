-- key: retail.inventory_variance_value
-- version: 1
-- grain: day
-- dims: [location_id, product_id]
-- unit: currency
-- aggregation: additive
-- sample_size: inventory counts
-- requires: [inventory_snapshot, product]
-- Rules: RET-INV-001 "Value Variance = (Physical − Book) × Unit Cost"; RET-INV-010
-- (book > physical). Additive per count (plan D contract): each counted day adds its variance.
SELECT i.location_id, i.product_id,
       i.snapshot_date                                        AS period_date,
       SUM((i.counted_qty - i.book_qty) * p.unit_cost)        AS value,
       COUNT(*)                                               AS sample_size
FROM inventory_snapshot i
LEFT JOIN product p ON p.product_id = i.product_id
WHERE i.snapshot_date >= :from AND i.snapshot_date < :to
GROUP BY 1, 2, 3
