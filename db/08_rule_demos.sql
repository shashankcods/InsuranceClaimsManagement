-- =====================================================================
-- 08_rule_demos.sql  --  every business rule (BR1-BR10) and transaction
-- demo, on a dedicated demo customer. Run with --force so the script keeps
-- going after each expected error; output: docs/outputs/08_rule_demos.txt
-- Self-cleaning: demo rows are removed at the start AND at the end, so the
-- demo never leaks into reports or into the ML training data.
-- =====================================================================

DROP PROCEDURE IF EXISTS demo_cleanup;
DELIMITER $$
CREATE PROCEDURE demo_cleanup(IN p_email VARCHAR(120))
BEGIN
    -- payouts first (claim_payout -> claim is ON DELETE RESTRICT);
    -- deleting claims cascades to documents, assessments and the audit log
    DELETE po FROM claim_payout po JOIN claim c ON c.claim_id = po.claim_id
      JOIN policy p ON p.policy_id = c.policy_id JOIN customer cu ON cu.customer_id = p.customer_id
     WHERE cu.email = p_email;
    DELETE c FROM claim c JOIN policy p ON p.policy_id = c.policy_id
      JOIN customer cu ON cu.customer_id = p.customer_id WHERE cu.email = p_email;
    DELETE p FROM policy p JOIN customer cu ON cu.customer_id = p.customer_id WHERE cu.email = p_email;
    DELETE FROM customer WHERE email = p_email;
END$$
DELIMITER ;

SET @demo_email = 'rule.demo@example.com';
CALL demo_cleanup(@demo_email);

-- ---------------- setup: a customer and a Health policy ----------------
INSERT INTO customer (first_name, last_name, dob, gender, email, phone, address_line, pincode)
VALUES ('Rule', 'Demo', '1990-01-01', 'M', @demo_email, '9000000001', '1, MNNIT Campus', '211004');
SELECT * FROM v_customer_directory WHERE customer_id = LAST_INSERT_ID();
SELECT customer_id INTO @cust FROM customer WHERE email = @demo_email;

-- F2: sell a policy (premium computed, number assigned, first instalment raised)
CALL sp_sell_policy(@cust, 1, 1, DATE_SUB(CURRENT_DATE, INTERVAL 60 DAY), 12, 500000, 'ANNUAL', @pol, @polno);
SELECT policy_id, policy_number, sum_assured, premium_amount, status FROM policy WHERE policy_id = @pol;
SELECT payment_id, instalment_no, due_date, amount, status FROM premium_payment WHERE policy_id = @pol;
UPDATE premium_payment SET status = 'PAID', paid_on = CURRENT_DATE, method = 'UPI' WHERE policy_id = @pol;

-- F2 rule: cover outside the product range is refused (Health max is 25,00,000)
CALL sp_sell_policy(@cust, 1, 1, CURRENT_DATE, 12, 99000000, 'ANNUAL', @x, @y);

-- ---------------- CHECK constraints (errno 3819) ----------------
INSERT INTO pincode (pincode, city, state) VALUES ('21A00', 'Prayagraj', 'Uttar Pradesh');   -- bad format
UPDATE premium_payment SET status = 'PAID', paid_on = NULL WHERE policy_id = @pol;           -- PAID needs paid_on
-- a customer must live at a known pincode (FK, errno 1452)
INSERT INTO customer (first_name, last_name, dob, gender, email, phone, address_line, pincode)
VALUES ('No', 'Pin', '1990-01-01', 'M', 'no.pin@example.com', '9000000002', 'x', '999999');

-- ---------------- BR2, BR3 on claim insert ----------------
-- BR2 incident before the policy started
CALL sp_file_claim(@pol, 1, 'HOSPITALISATION', DATE_SUB(CURRENT_DATE, INTERVAL 400 DAY), 50000, 'BR2 demo', @c, @cn);
-- BR3 claimed amount above the sum assured
CALL sp_file_claim(@pol, 1, 'HOSPITALISATION', DATE_SUB(CURRENT_DATE, INTERVAL 10 DAY), 600000, 'BR3 demo', @c, @cn);

-- ---------------- valid claim #1 ----------------
CALL sp_file_claim(@pol, 1, 'HOSPITALISATION', DATE_SUB(CURRENT_DATE, INTERVAL 10 DAY), 300000, 'Appendix surgery', @claim1, @cn1);
SELECT claim_id, claim_number, status, claimed_amount FROM claim WHERE claim_id = @claim1;

-- ---------------- BR4 status machine ----------------
UPDATE claim SET status = 'APPROVED' WHERE claim_id = @claim1;          -- skip review: refused
UPDATE claim SET status = 'UNDER_REVIEW' WHERE claim_id = @claim1;      -- no adjuster: refused
CALL sp_start_review(@claim1, 1);                                       -- adjuster 1, limit 2,00,000
SELECT claim_id, status, adjuster_id FROM claim WHERE claim_id = @claim1;
UPDATE claim SET claimed_amount = 1 WHERE claim_id = @claim1;           -- frozen after review starts
-- NEEDS_INFO: recorded as an assessment, claim stays UNDER_REVIEW
CALL sp_request_info(@claim1, 1, 'Please upload the discharge summary');
SELECT c.status, a.decision, a.remarks FROM claim c JOIN claim_assessment a ON a.claim_id = c.claim_id
 WHERE c.claim_id = @claim1;

-- ---------------- BR5 assessment limits ----------------
CALL sp_approve_claim(@claim1, 1, 300000, 'over the adjuster limit');    -- 3,00,000 > 2,00,000
CALL sp_approve_claim(@claim1, 15, 350000, 'over the claimed amount');   -- 3,50,000 > 3,00,000

-- ---------------- BR6 payout guards ----------------
INSERT INTO claim_payout (claim_id, amount, reference_no) VALUES (@claim1, 100, 'DEMO-EARLY');  -- not approved yet
CALL sp_approve_claim(@claim1, 12, 250000, 'Approved after document check');
INSERT INTO claim_payout (claim_id, amount, reference_no) VALUES (@claim1, 260000, 'DEMO-OVER'); -- > approved

-- ---------------- BR7 payout flips status to PAID ----------------
CALL sp_pay_claim(@claim1, 'NEFT', @payout1, @ref1);
SELECT c.claim_id, c.status, po.amount, po.reference_no
  FROM claim c JOIN claim_payout po ON po.claim_id = c.claim_id WHERE c.claim_id = @claim1;

-- ---------------- TRANSACTION 2: forced failure rolls everything back ----------------
-- claim #2 for 3,00,000: approving all of it would push total payouts on the
-- policy to 5,50,000 > sum assured 5,00,000 (BR6). The payout fails, so the
-- assessment AND the APPROVED status inserted earlier in the same procedure
-- are rolled back as well.
CALL sp_file_claim(@pol, 1, 'HOSPITALISATION', DATE_SUB(CURRENT_DATE, INTERVAL 5 DAY), 300000, 'Second admission', @claim2, @cn2);
CALL sp_start_review(@claim2, 15);
CALL sp_approve_and_pay_claim(@claim2, 15, 300000, 'full amount', 'NEFT', @payout2, @ref2);
SELECT claim_id, status FROM claim WHERE claim_id = @claim2;
SELECT COUNT(*) AS assessments_left_behind FROM claim_assessment WHERE claim_id = @claim2;

-- ---------------- TRANSACTION 1: atomic approve-and-pay succeeds ----------------
CALL sp_approve_and_pay_claim(@claim2, 15, 200000, 'capped at remaining cover', 'NEFT', @payout2, @ref2);
SELECT c.claim_id, c.status, po.amount, @ref2 AS reference
  FROM claim c JOIN claim_payout po ON po.claim_id = c.claim_id WHERE c.claim_id = @claim2;

-- ---------------- BR10 audit trail ----------------
SELECT claim_id, old_status, new_status, changed_at, changed_by
  FROM claim_status_log WHERE claim_id IN (@claim1, @claim2) ORDER BY log_id;

-- ---------------- TRANSACTION 3: SAVEPOINT / ROLLBACK TO ----------------
START TRANSACTION;
INSERT INTO nominee (policy_id, full_name, relationship, share_pct) VALUES (@pol, 'Asha Demo', 'SPOUSE', 50);
SAVEPOINT after_spouse;
INSERT INTO nominee (policy_id, full_name, relationship, share_pct) VALUES (@pol, 'Wrong Entry', 'OTHER', 30);
ROLLBACK TO SAVEPOINT after_spouse;
INSERT INTO nominee (policy_id, full_name, relationship, share_pct) VALUES (@pol, 'Ravi Demo', 'SON', 40);
COMMIT;
SELECT full_name, relationship, share_pct FROM nominee WHERE policy_id = @pol;

-- ---------------- BR8 nominee shares <= 100% ----------------
INSERT INTO nominee (policy_id, full_name, relationship, share_pct) VALUES (@pol, 'Too Much', 'DAUGHTER', 20); -- 110%
UPDATE nominee SET share_pct = 70 WHERE policy_id = @pol AND full_name = 'Ravi Demo';                         -- 120%
INSERT INTO nominee (policy_id, full_name, relationship, share_pct) VALUES (@pol, 'Meena Demo', 'DAUGHTER', 10); -- 100%: ok
SELECT SUM(share_pct) AS total_share FROM nominee WHERE policy_id = @pol;

-- ---------------- F3 / BR1 / BR9 premium lifecycle ----------------
-- Policy B: quarterly Motor policy started 200 days ago, nothing paid
CALL sp_sell_policy(@cust, 2, 1, DATE_SUB(CURRENT_DATE, INTERVAL 200 DAY), 12, 600000, 'QUARTERLY', @polB, @polBno);
CALL sp_generate_instalments(CURRENT_DATE, @created);
SELECT @created AS instalments_created_by_batch;
SELECT payment_id, instalment_no, due_date, status FROM premium_payment WHERE policy_id = @polB ORDER BY instalment_no;
CALL sp_lapse_overdue_policies(30, @lapsed);
SELECT @lapsed AS policies_lapsed, (SELECT status FROM policy WHERE policy_id = @polB) AS policy_b_status;

-- BR1: no claim on a LAPSED policy
CALL sp_file_claim(@polB, 80, 'VEHICLE_DAMAGE', DATE_SUB(CURRENT_DATE, INTERVAL 3 DAY), 40000, 'BR1 demo', @c, @cn);

-- BR9: pay the overdue instalments one by one; the policy re-activates after the last
SELECT MIN(payment_id), MAX(payment_id) INTO @firstB, @lastB FROM premium_payment
 WHERE policy_id = @polB AND due_date < CURRENT_DATE;
CALL sp_pay_premium(@firstB, 'UPI');
SELECT status AS after_first_payment FROM policy WHERE policy_id = @polB;
UPDATE premium_payment SET status = 'PAID', paid_on = CURRENT_DATE, method = 'UPI'
 WHERE policy_id = @polB AND due_date < CURRENT_DATE AND status <> 'PAID';
SELECT status AS after_all_overdue_paid FROM policy WHERE policy_id = @polB;

-- BR1 with a CANCELLED policy
UPDATE policy SET status = 'CANCELLED' WHERE policy_id = @polB;
CALL sp_file_claim(@polB, 80, 'VEHICLE_DAMAGE', DATE_SUB(CURRENT_DATE, INTERVAL 3 DAY), 40000, 'BR1 demo', @c, @cn);

-- ---------------- FK and UNIQUE errors (1451/1452/1062) ----------------
INSERT INTO claim_document (claim_id, doc_type, file_name) VALUES (999999, 'PHOTO', 'x.jpg');  -- 1452
DELETE FROM policy_type WHERE type_id = 1;
INSERT INTO customer (first_name, last_name, dob, gender, email, phone, address_line, pincode)
VALUES ('Dup', 'Email', '1990-01-01', 'M', @demo_email, '9000000003', 'x', '211004');

-- ---------------- remove every demo row again ----------------
CALL demo_cleanup(@demo_email);
SELECT COUNT(*) AS demo_customers_left FROM customer WHERE email = @demo_email;
DROP PROCEDURE demo_cleanup;
