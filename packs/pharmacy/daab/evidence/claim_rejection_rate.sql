-- key: pharmacy.claim_rejection_rate
SELECT claim_id, submitted_at, prescription_id, payer, billed_amount, is_rejected, rejection_code, _source_ref
FROM claim
WHERE submitted_at >= :from AND submitted_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
ORDER BY is_rejected DESC, submitted_at, claim_id
