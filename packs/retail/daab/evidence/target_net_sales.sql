-- key: retail.target_net_sales
SELECT location_id, metric_key, period, value, _source_ref
FROM target
WHERE metric_key = 'net_sales'
  AND period >= :from AND period < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
ORDER BY period
