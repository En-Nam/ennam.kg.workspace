-- key: pharmacy.claim_rejection_rate
-- version: 1
-- grain: day
-- dims: [location_id]
-- unit: percent
-- aggregation: ratio
-- sample_size: claims
-- requires: [claim]
-- lookback_days: 14
-- Rules: PH-CLAIM-001 (FND-005). Every claim counts (spec §6.2). Longer lookback:
-- claims change status days after submission.
SELECT location_id,
       CAST(submitted_at AS date)            AS period_date,
       COUNT(*) FILTER (WHERE is_rejected)   AS numerator,
       COUNT(*)                              AS denominator,
       COUNT(*)                              AS sample_size
FROM claim
WHERE submitted_at >= :from AND submitted_at < :to
GROUP BY 1, 2
