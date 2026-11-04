-- =====================================================================
-- 03_procedures.sql  --  stored functions and procedures
-- Functions cannot control transactions, so every atomic operation is a
-- PROCEDURE with OUT parameters. Pattern used by each public procedure:
--     DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
--     START TRANSACTION;  SELECT ... FOR UPDATE;  ...  COMMIT;
-- core_* procedures hold the shared logic WITHOUT transaction control, so
-- they can be composed (sp_approve_and_pay_claim = approve + pay, atomically).
-- =====================================================================

DROP FUNCTION  IF EXISTS fn_freq_months;
DROP FUNCTION  IF EXISTS fn_instalments_per_year;
DROP FUNCTION  IF EXISTS fn_annual_premium;
DROP PROCEDURE IF EXISTS sp_sell_policy;
DROP PROCEDURE IF EXISTS sp_file_claim;
DROP PROCEDURE IF EXISTS core_lock_claim;
DROP PROCEDURE IF EXISTS core_approve_claim;
DROP PROCEDURE IF EXISTS core_pay_claim;
DROP PROCEDURE IF EXISTS sp_start_review;
DROP PROCEDURE IF EXISTS sp_approve_claim;
DROP PROCEDURE IF EXISTS sp_pay_claim;
DROP PROCEDURE IF EXISTS sp_approve_and_pay_claim;
DROP PROCEDURE IF EXISTS sp_reject_claim;
DROP PROCEDURE IF EXISTS sp_request_info;
DROP PROCEDURE IF EXISTS sp_register_model;
DROP PROCEDURE IF EXISTS sp_pay_premium;
DROP PROCEDURE IF EXISTS sp_generate_instalments;
DROP PROCEDURE IF EXISTS sp_lapse_overdue_policies;
DROP PROCEDURE IF EXISTS sp_expire_policies;

DELIMITER $$

-- ---------------------------------------------------------------------
-- Helper functions
-- ---------------------------------------------------------------------
CREATE FUNCTION fn_freq_months(p_freq VARCHAR(12)) RETURNS INT
DETERMINISTIC NO SQL
BEGIN
    RETURN CASE p_freq WHEN 'MONTHLY' THEN 1 WHEN 'QUARTERLY' THEN 3
                       WHEN 'HALF_YEARLY' THEN 6 WHEN 'ANNUAL' THEN 12 ELSE NULL END;
END$$

CREATE FUNCTION fn_instalments_per_year(p_freq VARCHAR(12)) RETURNS INT
DETERMINISTIC NO SQL
BEGIN
    RETURN CASE p_freq WHEN 'MONTHLY' THEN 12 WHEN 'QUARTERLY' THEN 4
                       WHEN 'HALF_YEARLY' THEN 2 ELSE 1 END;
END$$

-- Annual premium = sum assured x base rate, loaded 2% per year of age above 30
-- for Health and Life products.
CREATE FUNCTION fn_annual_premium(p_type_id INT, p_sum DECIMAL(12,2), p_age INT)
RETURNS DECIMAL(12,2)
READS SQL DATA
BEGIN
    DECLARE v_rate DECIMAL(5,3);
    DECLARE v_name VARCHAR(30);
    DECLARE v_load DECIMAL(6,3) DEFAULT 1.000;
    SELECT base_rate_pct, type_name INTO v_rate, v_name FROM policy_type WHERE type_id = p_type_id;
    IF v_name IN ('Health', 'Life') THEN
        SET v_load = 1 + GREATEST(p_age - 30, 0) * 0.02;
    END IF;
    RETURN ROUND(p_sum * v_rate / 100 * v_load, 2);
END$$

-- ---------------------------------------------------------------------
-- F2 sell a policy: validate cover (trigger), compute premium,
-- assign the business number, create the first instalment. Atomic.
-- ---------------------------------------------------------------------
CREATE PROCEDURE sp_sell_policy(
    IN  p_customer_id INT,
    IN  p_type_id     INT,
    IN  p_agent_id    INT,
    IN  p_start_date  DATE,
    IN  p_term_months INT,
    IN  p_sum_assured DECIMAL(12,2),
    IN  p_frequency   VARCHAR(12),
    OUT p_policy_id   INT,
    OUT p_policy_number VARCHAR(40))
BEGIN
    DECLARE v_age INT;
    DECLARE v_annual DECIMAL(12,2);
    DECLARE v_instalment DECIMAL(12,2);
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;

    IF p_term_months IS NULL OR p_term_months < 1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Term must be at least one month';
    END IF;

    START TRANSACTION;

    SELECT TIMESTAMPDIFF(YEAR, dob, p_start_date) INTO v_age
      FROM customer WHERE customer_id = p_customer_id;
    IF v_age IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Customer does not exist';
    END IF;

    SET v_annual = fn_annual_premium(p_type_id, p_sum_assured, v_age);
    IF v_annual IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unknown policy type';
    END IF;
    SET v_instalment = IF(p_frequency = 'SINGLE',
                          ROUND(v_annual * p_term_months / 12, 2),
                          ROUND(v_annual / fn_instalments_per_year(p_frequency), 2));

    INSERT INTO policy (customer_id, type_id, agent_id, start_date, end_date,
                        sum_assured, premium_amount, payment_frequency, status)
    VALUES (p_customer_id, p_type_id, p_agent_id, p_start_date,
            DATE_SUB(DATE_ADD(p_start_date, INTERVAL p_term_months MONTH), INTERVAL 1 DAY),
            p_sum_assured, GREATEST(v_instalment, 1), p_frequency, 'ACTIVE');

    SET p_policy_id = LAST_INSERT_ID();
    SET p_policy_number = CONCAT('POL-', YEAR(p_start_date), '-', LPAD(p_policy_id, 6, '0'));
    UPDATE policy SET policy_number = p_policy_number WHERE policy_id = p_policy_id;

    INSERT INTO premium_payment (policy_id, instalment_no, due_date, amount, status)
    VALUES (p_policy_id, 1, p_start_date, GREATEST(v_instalment, 1), 'PENDING');

    COMMIT;
END$$

-- ---------------------------------------------------------------------
-- F4 file a claim (BR1-BR3 checked by trg_claim_bi)
-- ---------------------------------------------------------------------
CREATE PROCEDURE sp_file_claim(
    IN  p_policy_id     INT,
    IN  p_provider_id   INT,
    IN  p_claim_type    VARCHAR(25),
    IN  p_incident_date DATE,
    IN  p_amount        DECIMAL(12,2),
    IN  p_description   VARCHAR(500),
    OUT p_claim_id      INT,
    OUT p_claim_number  VARCHAR(40))
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
    START TRANSACTION;

    INSERT INTO claim (policy_id, provider_id, claim_type, incident_date, claimed_amount, description)
    VALUES (p_policy_id, p_provider_id, p_claim_type, p_incident_date, p_amount, p_description);

    SET p_claim_id = LAST_INSERT_ID();
    SET p_claim_number = CONCAT('CLM-', YEAR(CURRENT_DATE), '-', LPAD(p_claim_id, 6, '0'));
    UPDATE claim SET claim_number = p_claim_number WHERE claim_id = p_claim_id;

    COMMIT;
END$$

-- ---------------------------------------------------------------------
-- core_* building blocks (caller owns the transaction)
-- ---------------------------------------------------------------------

-- Row-lock the claim and check it is in the expected status.
-- A second session doing the same waits here until the first commits,
-- then sees the NEW status and fails the check (concurrency demo).
CREATE PROCEDURE core_lock_claim(IN p_claim_id INT, IN p_expected VARCHAR(15))
BEGIN
    DECLARE v_status VARCHAR(15);
    DECLARE v_msg VARCHAR(255);
    SELECT status INTO v_status FROM claim WHERE claim_id = p_claim_id FOR UPDATE;
    IF v_status IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Claim does not exist';
    END IF;
    IF v_status <> p_expected THEN
        SET v_msg = CONCAT('Claim ', p_claim_id, ' is ', v_status, ', expected ', p_expected);
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
    END IF;
END$$

CREATE PROCEDURE core_approve_claim(
    IN p_claim_id INT, IN p_adjuster_id INT, IN p_amount DECIMAL(12,2), IN p_remarks VARCHAR(500))
BEGIN
    CALL core_lock_claim(p_claim_id, 'UNDER_REVIEW');
    INSERT INTO claim_assessment (claim_id, adjuster_id, decision, approved_amount, remarks)
    VALUES (p_claim_id, p_adjuster_id, 'APPROVED', p_amount, p_remarks);       -- BR5
    UPDATE claim SET status = 'APPROVED', adjuster_id = p_adjuster_id
     WHERE claim_id = p_claim_id;                                              -- BR4
END$$

CREATE PROCEDURE core_pay_claim(
    IN p_claim_id INT, IN p_method VARCHAR(20), OUT p_payout_id INT, OUT p_reference VARCHAR(40))
BEGIN
    DECLARE v_amount DECIMAL(12,2);
    CALL core_lock_claim(p_claim_id, 'APPROVED');
    SELECT approved_amount INTO v_amount
      FROM claim_assessment
     WHERE claim_id = p_claim_id AND decision = 'APPROVED'
     ORDER BY assessed_on DESC, assessment_id DESC LIMIT 1;
    SET p_reference = CONCAT('PAY-', DATE_FORMAT(NOW(), '%Y%m%d'), '-', LPAD(p_claim_id, 6, '0'));
    INSERT INTO claim_payout (claim_id, amount, method, reference_no)
    VALUES (p_claim_id, v_amount, COALESCE(p_method, 'NEFT'), p_reference);     -- BR6, BR7
    SET p_payout_id = LAST_INSERT_ID();
END$$

-- ---------------------------------------------------------------------
-- F5 workflow procedures (each one transaction)
-- ---------------------------------------------------------------------
CREATE PROCEDURE sp_start_review(IN p_claim_id INT, IN p_adjuster_id INT)
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
    START TRANSACTION;
    CALL core_lock_claim(p_claim_id, 'SUBMITTED');
    UPDATE claim SET adjuster_id = p_adjuster_id, status = 'UNDER_REVIEW'
     WHERE claim_id = p_claim_id;
    COMMIT;
END$$

CREATE PROCEDURE sp_approve_claim(
    IN p_claim_id INT, IN p_adjuster_id INT, IN p_amount DECIMAL(12,2), IN p_remarks VARCHAR(500))
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
    START TRANSACTION;
    CALL core_approve_claim(p_claim_id, p_adjuster_id, p_amount, p_remarks);
    COMMIT;
END$$

CREATE PROCEDURE sp_pay_claim(
    IN p_claim_id INT, IN p_method VARCHAR(20), OUT p_payout_id INT, OUT p_reference VARCHAR(40))
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
    START TRANSACTION;
    CALL core_pay_claim(p_claim_id, p_method, p_payout_id, p_reference);
    COMMIT;
END$$

-- F6: approve and pay as ONE atomic unit. If the payout fails (e.g. BR6
-- policy cap), the assessment and the APPROVED status are rolled back too.
CREATE PROCEDURE sp_approve_and_pay_claim(
    IN p_claim_id INT, IN p_adjuster_id INT, IN p_amount DECIMAL(12,2), IN p_remarks VARCHAR(500),
    IN p_method VARCHAR(20), OUT p_payout_id INT, OUT p_reference VARCHAR(40))
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
    START TRANSACTION;
    CALL core_approve_claim(p_claim_id, p_adjuster_id, p_amount, p_remarks);
    CALL core_pay_claim(p_claim_id, p_method, p_payout_id, p_reference);
    COMMIT;
END$$

CREATE PROCEDURE sp_reject_claim(
    IN p_claim_id INT, IN p_adjuster_id INT, IN p_remarks VARCHAR(500), IN p_is_fraud TINYINT)
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
    START TRANSACTION;
    CALL core_lock_claim(p_claim_id, 'UNDER_REVIEW');
    INSERT INTO claim_assessment (claim_id, adjuster_id, decision, remarks)
    VALUES (p_claim_id, p_adjuster_id, 'REJECTED', p_remarks);
    UPDATE claim
       SET status = 'REJECTED', adjuster_id = p_adjuster_id,
           fraud_flag = IF(COALESCE(p_is_fraud, 0) = 1, 1, fraud_flag)
     WHERE claim_id = p_claim_id;
    COMMIT;
END$$

-- Ask the customer for more documents: recorded as a NEEDS_INFO assessment,
-- the claim stays UNDER_REVIEW (no status change, so no audit row).
CREATE PROCEDURE sp_request_info(IN p_claim_id INT, IN p_adjuster_id INT, IN p_remarks VARCHAR(500))
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
    START TRANSACTION;
    CALL core_lock_claim(p_claim_id, 'UNDER_REVIEW');
    INSERT INTO claim_assessment (claim_id, adjuster_id, decision, remarks)
    VALUES (p_claim_id, p_adjuster_id, 'NEEDS_INFO', COALESCE(p_remarks, 'Additional documents requested'));
    COMMIT;
END$$

-- ---------------------------------------------------------------------
-- ML model registry: exactly one active model, switched atomically
-- ---------------------------------------------------------------------
CREATE PROCEDURE sp_register_model(
    IN p_name VARCHAR(60), IN p_threshold DECIMAL(5,4), IN p_auc DECIMAL(5,4), IN p_n INT, OUT p_model_id INT)
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
    START TRANSACTION;
    UPDATE fraud_model SET is_active = 0 WHERE is_active = 1;
    INSERT INTO fraud_model (model_name, threshold, test_roc_auc, n_trained, is_active)
    VALUES (p_name, p_threshold, p_auc, p_n, 1);
    SET p_model_id = LAST_INSERT_ID();
    COMMIT;
END$$

-- ---------------------------------------------------------------------
-- F3 premium lifecycle
-- ---------------------------------------------------------------------

-- Pay one instalment (BR9 re-activation happens in trg_payment_au)
CREATE PROCEDURE sp_pay_premium(IN p_payment_id INT, IN p_method VARCHAR(12))
BEGIN
    DECLARE v_status VARCHAR(10);
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
    START TRANSACTION;
    SELECT status INTO v_status FROM premium_payment WHERE payment_id = p_payment_id FOR UPDATE;
    IF v_status IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Instalment does not exist';
    END IF;
    IF v_status = 'PAID' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Instalment is already paid';
    END IF;
    UPDATE premium_payment
       SET status = 'PAID', paid_on = CURRENT_DATE, method = COALESCE(p_method, 'UPI')
     WHERE payment_id = p_payment_id;
    COMMIT;
END$$

-- Raise the next instalment for every ACTIVE/LAPSED policy whose next due
-- date is on or before p_upto (and inside the term). Repeats until caught up.
CREATE PROCEDURE sp_generate_instalments(IN p_upto DATE, OUT p_created INT)
BEGIN
    DECLARE v_rows INT DEFAULT 1;
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
    SET p_created = 0;
    START TRANSACTION;
    WHILE v_rows > 0 DO
        INSERT INTO premium_payment (policy_id, instalment_no, due_date, amount, status)
        SELECT p.policy_id, last.max_no + 1,
               DATE_ADD(last.max_due, INTERVAL fn_freq_months(p.payment_frequency) MONTH),
               p.premium_amount, 'PENDING'
          FROM policy p
          JOIN (SELECT policy_id, MAX(instalment_no) AS max_no, MAX(due_date) AS max_due
                  FROM premium_payment GROUP BY policy_id) last ON last.policy_id = p.policy_id
         WHERE p.status IN ('ACTIVE', 'LAPSED')
           AND p.payment_frequency <> 'SINGLE'
           AND DATE_ADD(last.max_due, INTERVAL fn_freq_months(p.payment_frequency) MONTH) <= p_upto
           AND DATE_ADD(last.max_due, INTERVAL fn_freq_months(p.payment_frequency) MONTH) <= p.end_date;
        SET v_rows = ROW_COUNT();
        SET p_created = p_created + v_rows;
    END WHILE;
    COMMIT;
END$$

-- Batch: lapse ACTIVE policies with an instalment unpaid beyond the grace period
CREATE PROCEDURE sp_lapse_overdue_policies(IN p_grace_days INT, OUT p_lapsed INT)
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
    START TRANSACTION;
    UPDATE policy p
       SET p.status = 'LAPSED'
     WHERE p.status = 'ACTIVE'
       AND EXISTS (SELECT 1 FROM premium_payment pp
                    WHERE pp.policy_id = p.policy_id
                      AND pp.status <> 'PAID'
                      AND pp.due_date < DATE_SUB(CURRENT_DATE, INTERVAL p_grace_days DAY));
    SET p_lapsed = ROW_COUNT();
    COMMIT;
END$$

-- Batch: policies past their end date become EXPIRED
CREATE PROCEDURE sp_expire_policies(OUT p_expired INT)
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
    START TRANSACTION;
    UPDATE policy SET status = 'EXPIRED'
     WHERE status IN ('ACTIVE', 'LAPSED') AND end_date < CURRENT_DATE;
    SET p_expired = ROW_COUNT();
    COMMIT;
END$$

DELIMITER ;
