-- =====================================================================
-- 02_triggers.sql  --  business rules enforced inside the database
-- MySQL notes: no WHEN clause (use IF), one trigger per event/timing,
-- errors raised with SIGNAL SQLSTATE '45000' (client errno 1644),
-- a trigger never modifies the table that fired it (error 1442).
-- Run with the mysql CLI (DELIMITER is a client command).
-- =====================================================================

DROP TRIGGER IF EXISTS trg_policy_bi;
DROP TRIGGER IF EXISTS trg_claim_bi;
DROP TRIGGER IF EXISTS trg_claim_ai;
DROP TRIGGER IF EXISTS trg_claim_bu;
DROP TRIGGER IF EXISTS trg_claim_au;
DROP TRIGGER IF EXISTS trg_assessment_bi;
DROP TRIGGER IF EXISTS trg_payout_bi;
DROP TRIGGER IF EXISTS trg_payout_ai;
DROP TRIGGER IF EXISTS trg_nominee_ai;
DROP TRIGGER IF EXISTS trg_nominee_au;
DROP TRIGGER IF EXISTS trg_payment_ai;
DROP TRIGGER IF EXISTS trg_payment_au;

DELIMITER $$

-- ---------------------------------------------------------------------
-- F2: cover must lie inside the product's min/max and term limit.
-- A CHECK constraint cannot read another table, so this is a trigger.
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_policy_bi
BEFORE INSERT ON policy
FOR EACH ROW
BEGIN
    DECLARE v_min DECIMAL(12,2);
    DECLARE v_max DECIMAL(12,2);
    DECLARE v_term INT;
    DECLARE v_msg VARCHAR(255);

    SELECT min_sum_assured, max_sum_assured, max_term_years
      INTO v_min, v_max, v_term
      FROM policy_type WHERE type_id = NEW.type_id;

    IF v_min IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unknown policy type';
    END IF;
    IF NEW.sum_assured < v_min OR NEW.sum_assured > v_max THEN
        SET v_msg = CONCAT('Sum assured ', NEW.sum_assured, ' is outside the product range ', v_min, ' - ', v_max);
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
    END IF;
    IF NEW.end_date > DATE_ADD(NEW.start_date, INTERVAL v_term YEAR) THEN
        SET v_msg = CONCAT('Policy term exceeds the product maximum of ', v_term, ' year(s)');
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
    END IF;
END$$

-- ---------------------------------------------------------------------
-- BR1 no claim on a LAPSED/CANCELLED policy
-- BR2 incident date inside the policy period
-- BR3 claimed amount <= sum assured
-- Also: a claim always enters the workflow as SUBMITTED.
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_claim_bi
BEFORE INSERT ON claim
FOR EACH ROW
BEGIN
    DECLARE v_status VARCHAR(10);
    DECLARE v_start DATE;
    DECLARE v_end DATE;
    DECLARE v_sum DECIMAL(12,2);
    DECLARE v_msg VARCHAR(255);

    SELECT status, start_date, end_date, sum_assured
      INTO v_status, v_start, v_end, v_sum
      FROM policy WHERE policy_id = NEW.policy_id;

    IF v_status IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Policy does not exist';
    END IF;
    IF v_status IN ('LAPSED', 'CANCELLED') THEN
        SET v_msg = CONCAT('BR1: cannot file a claim on a ', v_status, ' policy');
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
    END IF;
    IF NEW.incident_date < v_start OR NEW.incident_date > v_end THEN
        SET v_msg = CONCAT('BR2: incident date ', NEW.incident_date, ' is outside the policy period ',
                           v_start, ' to ', v_end);
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
    END IF;
    IF NEW.claimed_amount > v_sum THEN
        SET v_msg = CONCAT('BR3: claimed amount ', NEW.claimed_amount, ' exceeds the sum assured ', v_sum);
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
    END IF;
    IF NEW.status <> 'SUBMITTED' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'A new claim must start in status SUBMITTED';
    END IF;
END$$

-- BR10 (insert half): log the initial status
CREATE TRIGGER trg_claim_ai
AFTER INSERT ON claim
FOR EACH ROW
BEGIN
    INSERT INTO claim_status_log (claim_id, old_status, new_status, changed_at, changed_by)
    VALUES (NEW.claim_id, NULL, NEW.status, NEW.filed_on, CURRENT_USER());
END$$

-- ---------------------------------------------------------------------
-- BR4 status machine:
--   SUBMITTED -> UNDER_REVIEW -> APPROVED | REJECTED ;  APPROVED -> PAID
-- plus guards: review needs an adjuster, a decision needs an assessment,
-- PAID needs a payout row, and the money fields freeze after submission.
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_claim_bu
BEFORE UPDATE ON claim
FOR EACH ROW
BEGIN
    DECLARE v_msg VARCHAR(255);

    IF NEW.status <> OLD.status THEN
        IF NOT (   (OLD.status = 'SUBMITTED'    AND NEW.status = 'UNDER_REVIEW')
                OR (OLD.status = 'UNDER_REVIEW' AND NEW.status IN ('APPROVED', 'REJECTED'))
                OR (OLD.status = 'APPROVED'     AND NEW.status = 'PAID')) THEN
            SET v_msg = CONCAT('BR4: illegal status change ', OLD.status, ' -> ', NEW.status);
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
        END IF;

        IF NEW.status = 'UNDER_REVIEW' AND NEW.adjuster_id IS NULL THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'BR4: a claim needs an adjuster before review';
        END IF;
        IF NEW.status IN ('APPROVED', 'REJECTED') AND NOT EXISTS (
               SELECT 1 FROM claim_assessment
                WHERE claim_id = NEW.claim_id AND decision = NEW.status) THEN
            SET v_msg = CONCAT('BR4: no ', NEW.status, ' assessment recorded for this claim');
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
        END IF;
        IF NEW.status = 'PAID' AND NOT EXISTS (
               SELECT 1 FROM claim_payout WHERE claim_id = NEW.claim_id) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'BR4: a claim becomes PAID only through a payout';
        END IF;
    END IF;

    IF OLD.status <> 'SUBMITTED'
       AND (NEW.claimed_amount <> OLD.claimed_amount OR NEW.policy_id <> OLD.policy_id
            OR NEW.incident_date <> OLD.incident_date) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Claim details are frozen once review has started';
    END IF;
END$$

-- BR10 (update half): log every status change.
-- @audit_ts lets the seed loader replay history with realistic timestamps.
CREATE TRIGGER trg_claim_au
AFTER UPDATE ON claim
FOR EACH ROW
BEGIN
    IF NEW.status <> OLD.status THEN
        INSERT INTO claim_status_log (claim_id, old_status, new_status, changed_at, changed_by)
        VALUES (NEW.claim_id, OLD.status, NEW.status, COALESCE(@audit_ts, NOW()), CURRENT_USER());
    END IF;
END$$

-- ---------------------------------------------------------------------
-- BR5 approval within the adjuster's limit and within the claimed amount
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_assessment_bi
BEFORE INSERT ON claim_assessment
FOR EACH ROW
BEGIN
    DECLARE v_status VARCHAR(15);
    DECLARE v_claimed DECIMAL(12,2);
    DECLARE v_limit DECIMAL(12,2);
    DECLARE v_msg VARCHAR(255);

    SELECT status, claimed_amount INTO v_status, v_claimed
      FROM claim WHERE claim_id = NEW.claim_id;
    SELECT approval_limit INTO v_limit
      FROM adjuster WHERE adjuster_id = NEW.adjuster_id;

    IF v_status <> 'UNDER_REVIEW' THEN
        SET v_msg = CONCAT('BR5: only a claim UNDER_REVIEW can be assessed (current: ', v_status, ')');
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
    END IF;
    IF NEW.decision = 'APPROVED' THEN
        IF NEW.approved_amount > v_limit THEN
            SET v_msg = CONCAT('BR5: approved amount ', NEW.approved_amount,
                               ' exceeds the adjuster approval limit ', v_limit);
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
        END IF;
        IF NEW.approved_amount > v_claimed THEN
            SET v_msg = CONCAT('BR5: approved amount ', NEW.approved_amount,
                               ' exceeds the claimed amount ', v_claimed);
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
        END IF;
    END IF;
END$$

-- ---------------------------------------------------------------------
-- BR6 payout needs an APPROVED claim, <= approved amount,
--     and total payouts on the policy <= sum assured
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_payout_bi
BEFORE INSERT ON claim_payout
FOR EACH ROW
BEGIN
    DECLARE v_status VARCHAR(15);
    DECLARE v_policy INT;
    DECLARE v_approved DECIMAL(12,2);
    DECLARE v_sum DECIMAL(12,2);
    DECLARE v_paid DECIMAL(14,2);
    DECLARE v_msg VARCHAR(255);

    SELECT status, policy_id INTO v_status, v_policy
      FROM claim WHERE claim_id = NEW.claim_id;

    IF v_status <> 'APPROVED' THEN
        SET v_msg = CONCAT('BR6: only an APPROVED claim can be paid (current: ', v_status, ')');
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
    END IF;

    SELECT approved_amount INTO v_approved
      FROM claim_assessment
     WHERE claim_id = NEW.claim_id AND decision = 'APPROVED'
     ORDER BY assessed_on DESC, assessment_id DESC
     LIMIT 1;
    IF NEW.amount > v_approved THEN
        SET v_msg = CONCAT('BR6: payout ', NEW.amount, ' exceeds the approved amount ', v_approved);
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
    END IF;

    SELECT p.sum_assured INTO v_sum FROM policy p WHERE p.policy_id = v_policy;
    SELECT COALESCE(SUM(cp.amount), 0) INTO v_paid
      FROM claim_payout cp JOIN claim c ON c.claim_id = cp.claim_id
     WHERE c.policy_id = v_policy;
    IF v_paid + NEW.amount > v_sum THEN
        SET v_msg = CONCAT('BR6: total payouts ', v_paid + NEW.amount,
                           ' would exceed the sum assured ', v_sum);
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
    END IF;
END$$

-- BR7 a payout flips the claim to PAID (fires trg_claim_bu/au in turn)
CREATE TRIGGER trg_payout_ai
AFTER INSERT ON claim_payout
FOR EACH ROW
BEGIN
    UPDATE claim SET status = 'PAID' WHERE claim_id = NEW.claim_id;
END$$

-- ---------------------------------------------------------------------
-- BR8 nominee shares per policy must not exceed 100%
-- (an AFTER trigger may READ its own table; the error rolls the row back)
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_nominee_ai
AFTER INSERT ON nominee
FOR EACH ROW
BEGIN
    DECLARE v_total DECIMAL(7,2);
    DECLARE v_msg VARCHAR(255);
    SELECT SUM(share_pct) INTO v_total FROM nominee WHERE policy_id = NEW.policy_id;
    IF v_total > 100 THEN
        SET v_msg = CONCAT('BR8: nominee shares for policy ', NEW.policy_id, ' would total ', v_total, '%');
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
    END IF;
END$$

CREATE TRIGGER trg_nominee_au
AFTER UPDATE ON nominee
FOR EACH ROW
BEGIN
    DECLARE v_total DECIMAL(7,2);
    DECLARE v_msg VARCHAR(255);
    SELECT SUM(share_pct) INTO v_total FROM nominee WHERE policy_id = NEW.policy_id;
    IF v_total > 100 THEN
        SET v_msg = CONCAT('BR8: nominee shares for policy ', NEW.policy_id, ' would total ', v_total, '%');
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
    END IF;
END$$

-- ---------------------------------------------------------------------
-- BR9 paying the last overdue instalment re-activates a LAPSED policy
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_payment_ai
AFTER INSERT ON premium_payment
FOR EACH ROW
BEGIN
    IF NEW.status = 'PAID' THEN
        UPDATE policy p
           SET p.status = 'ACTIVE'
         WHERE p.policy_id = NEW.policy_id
           AND p.status = 'LAPSED'
           AND p.end_date >= CURRENT_DATE
           AND NOT EXISTS (SELECT 1 FROM premium_payment pp
                            WHERE pp.policy_id = NEW.policy_id
                              AND pp.status <> 'PAID'
                              AND pp.due_date < CURRENT_DATE);
    END IF;
END$$

CREATE TRIGGER trg_payment_au
AFTER UPDATE ON premium_payment
FOR EACH ROW
BEGIN
    IF NEW.status = 'PAID' AND OLD.status <> 'PAID' THEN
        UPDATE policy p
           SET p.status = 'ACTIVE'
         WHERE p.policy_id = NEW.policy_id
           AND p.status = 'LAPSED'
           AND p.end_date >= CURRENT_DATE
           AND NOT EXISTS (SELECT 1 FROM premium_payment pp
                            WHERE pp.policy_id = NEW.policy_id
                              AND pp.status <> 'PAID'
                              AND pp.due_date < CURRENT_DATE);
    END IF;
END$$

DELIMITER ;
