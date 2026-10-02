-- key: retail.target_gross_margin_pct
SELECT location_id, metric_key, period, value, _source_ref
FROM target
WHERE metric_key = 'gross_margin_pct'
  AND period >= :from AND period < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
ORDER BY period
