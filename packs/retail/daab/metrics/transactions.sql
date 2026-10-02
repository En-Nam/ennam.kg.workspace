-- key: retail.transactions
-- version: 1
-- grain: day
-- dims: [location_id]
-- unit: count
-- aggregation: additive
-- sample_size: completed sales
-- requires: [sale]
-- Rules: RET-SALES-001 (transaction-count change, minimum volume).
SELECT location_id,
       CAST(sold_at AS date) AS period_date,
       COUNT(*)              AS value,
       COUNT(*)              AS sample_size
FROM sale
WHERE status = 'completed'
  AND sold_at >= :from AND sold_at < :to
GROUP BY 1, 2
