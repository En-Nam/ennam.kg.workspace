-- key: pharmacy.rx_revenue
SELECT c.claim_id, c.submitted_at, p.prescription_id, p.status,
       c.reimbursed_amount, c.patient_amount, c._source_ref
FROM claim c
JOIN prescription p ON p.prescription_id = c.prescription_id
WHERE NOT c.is_rejected
  AND p.status NOT IN ('reversed', 'cancelled')
  AND c.submitted_at >= :from AND c.submitted_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(c.location_id, '') = :dim_location_id)
  AND (:dim_product_id IS NULL OR COALESCE(p.product_id, '') = :dim_product_id)
ORDER BY c.submitted_at, c.claim_id
