-- key: retail.transactions
SELECT sale_id, sold_at, employee_id, gross_amount, discount_amount, net_amount, _source_ref
FROM sale
WHERE status = 'completed'
  AND sold_at >= :from AND sold_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
ORDER BY sold_at, sale_id
