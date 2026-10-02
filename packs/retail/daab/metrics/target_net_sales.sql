-- key: retail.target_net_sales
-- version: 1
-- grain: month
-- dims: [location_id]
-- unit: currency
-- aggregation: snapshot
-- sample_size: target rows
-- requires: [target]
-- Rules: RET-MARGIN-001 / RET-SALES-001 (customer target). Monthly target from the
-- uploaded file (mode=file, Plan C); LAAM prorates by days (spec §6.4).
SELECT location_id,
       period     AS period_date,
       value,
       1          AS sample_size
FROM target
WHERE metric_key = 'net_sales'
  AND period >= :from AND period < :to
