-- key: retail.target_gross_margin_pct
-- version: 1
-- grain: month
-- dims: [location_id]
-- unit: percent
-- aggregation: snapshot
-- sample_size: target rows
-- requires: [target]
-- Rules: RET-MARGIN-001 "Actual Gross Margin % − Target Gross Margin %".
SELECT location_id,
       period     AS period_date,
       value,
       1          AS sample_size
FROM target
WHERE metric_key = 'gross_margin_pct'
  AND period >= :from AND period < :to
