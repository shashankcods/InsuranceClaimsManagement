-- =====================================================================
-- 06_indexes.sql  --  secondary indexes for filters and sorts
-- InnoDB already indexes every PK, UNIQUE and FK column, so these target
-- the WHERE / ORDER BY patterns used by the views, reports and API.
-- MySQL has no partial indexes, so the "status = X" filters use composite
-- indexes with status as the leading column.
-- =====================================================================

-- policies by status and expiry (expiring-policies report, sp_expire_policies)
CREATE INDEX idx_policy_status_end   ON policy (status, end_date);
-- open-claims queue: WHERE status IN (...) ORDER BY filed_on
CREATE INDEX idx_claim_status_filed  ON claim (status, filed_on);
-- monthly claims trend / date-range scans
CREATE INDEX idx_claim_filed         ON claim (filed_on);
-- overdue premiums: WHERE status <> 'PAID' AND due_date < today
CREATE INDEX idx_payment_status_due  ON premium_payment (status, due_date);
-- documents per claim (already covered by the FK index; kept explicit for the report)
CREATE INDEX idx_document_claim      ON claim_document (claim_id, doc_type);
-- city lookups go through pincode (customer.pincode is already FK-indexed)
CREATE INDEX idx_pincode_city        ON pincode (city);
-- customer search by name
CREATE INDEX idx_customer_name       ON customer (last_name, first_name);
