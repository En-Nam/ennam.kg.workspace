-- key: retail.refund_rate
-- version: 1
-- grain: day
-- dims: [location_id, employee_id]
-- unit: percent
-- aggregation: ratio
-- sample_size: refunds
-- requires: [refund, sale]
-- Rules: RET-REF-001 "Refund Value Rate = Refund Value ÷ Net Sales Before Refunds × 100"
-- (plan D contract: value ratio); min_sample counts refunds, so sample_size = refunds.
-- Net sales is the sale header net_amount (all POS lines).
WITH x AS (
  SELECT location_id, employee_id, CAST(refunded_at AS date) AS period_date,
         amount AS refunded, CAST(0 AS numeric) AS sold, 1 AS refunds
  FROM refund
  WHERE refunded_at >= :from AND refunded_at < :to
  UNION ALL
  SELECT location_id, employee_id, CAST(sold_at AS date), 0, COALESCE(net_amount, 0), 0
  FROM sale
  WHERE status = 'completed' AND sold_at >= :from AND sold_at < :to
)
SELECT location_id, employee_id, period_date,
       SUM(refunded) AS numerator,
       SUM(sold)     AS denominator,
       SUM(refunds)  AS sample_size
FROM x
GROUP BY 1, 2, 3
