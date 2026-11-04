-- =====================================================================
-- 04_views.sql  --  10 views used by the API, reports and the ML module
-- =====================================================================

-- 1. One row per policy with holder, product, agent and payment position
CREATE OR REPLACE VIEW v_policy_overview AS
SELECT p.policy_id,
       p.policy_number,
       p.status,
       p.start_date,
       p.end_date,
       p.sum_assured,
       p.premium_amount,
       p.payment_frequency,
       c.customer_id,
       CONCAT(c.first_name, ' ', c.last_name)                 AS customer_name,
       pin.city,
       pt.type_id,
       pt.type_name,
       a.agent_id,
       CONCAT(a.first_name, ' ', a.last_name)                 AS agent_name,
       COALESCE(pay.premium_paid, 0)                          AS premium_paid,
       COALESCE(pay.overdue_instalments, 0)                   AS overdue_instalments,
       COALESCE(cl.claim_count, 0)                            AS claim_count,
       DATEDIFF(p.end_date, CURRENT_DATE)                     AS days_to_expiry
  FROM policy p
  JOIN customer    c   ON c.customer_id = p.customer_id
  JOIN pincode     pin ON pin.pincode   = c.pincode
  JOIN policy_type pt  ON pt.type_id    = p.type_id
  LEFT JOIN agent  a   ON a.agent_id    = p.agent_id
  LEFT JOIN (SELECT policy_id,
                    SUM(CASE WHEN status = 'PAID' THEN amount ELSE 0 END)         AS premium_paid,
                    SUM(status <> 'PAID' AND due_date < CURRENT_DATE)             AS overdue_instalments
               FROM premium_payment GROUP BY policy_id) pay ON pay.policy_id = p.policy_id
  LEFT JOIN (SELECT policy_id, COUNT(*) AS claim_count
               FROM claim GROUP BY policy_id) cl ON cl.policy_id = p.policy_id;

-- 2. One row per claim with everything the claims desk needs
CREATE OR REPLACE VIEW v_claim_summary AS
SELECT cl.claim_id,
       cl.claim_number,
       cl.status,
       cl.claim_type,
       cl.incident_date,
       cl.filed_on,
       cl.claimed_amount,
       ap.approved_amount,
       po.amount                                              AS paid_amount,
       po.paid_on,
       DATEDIFF(po.paid_on, cl.filed_on)                      AS days_to_settle,
       cl.fraud_flag,
       cl.fraud_score,
       -- bands follow the active model's tuned threshold (0.5 if none is registered):
       -- HIGH = model predicts fraud, MEDIUM = at least half way there
       CASE WHEN cl.fraud_score IS NULL THEN NULL
            WHEN cl.fraud_score >= fm.threshold     THEN 'HIGH'
            WHEN cl.fraud_score >= fm.threshold / 2 THEN 'MEDIUM'
            ELSE 'LOW' END                                    AS risk_band,
       p.policy_id,
       p.policy_number,
       pt.type_name,
       c.customer_id,
       CONCAT(c.first_name, ' ', c.last_name)                 AS customer_name,
       pr.provider_id,
       pr.name                                                AS provider_name,
       pr.is_network,
       ad.adjuster_id,
       CONCAT(ad.first_name, ' ', ad.last_name)               AS adjuster_name,
       (SELECT COUNT(*) FROM claim_document d WHERE d.claim_id = cl.claim_id) AS document_count
  FROM claim cl
  JOIN policy      p  ON p.policy_id   = cl.policy_id
  JOIN policy_type pt ON pt.type_id    = p.type_id
  JOIN customer    c  ON c.customer_id = p.customer_id
  LEFT JOIN provider pr ON pr.provider_id = cl.provider_id
  LEFT JOIN adjuster ad ON ad.adjuster_id = cl.adjuster_id
  LEFT JOIN claim_payout po ON po.claim_id = cl.claim_id
  CROSS JOIN (SELECT COALESCE(MAX(CASE WHEN is_active = 1 THEN threshold END), 0.5) AS threshold
                FROM fraud_model) fm
  LEFT JOIN (SELECT claim_id, approved_amount
               FROM (SELECT claim_id, approved_amount,
                            ROW_NUMBER() OVER (PARTITION BY claim_id
                                               ORDER BY assessed_on DESC, assessment_id DESC) AS rn
                       FROM claim_assessment WHERE decision = 'APPROVED') x
              WHERE rn = 1) ap ON ap.claim_id = cl.claim_id;

-- 3. Agent performance and commission (commission on premium actually collected)
CREATE OR REPLACE VIEW v_agent_performance AS
SELECT a.agent_id,
       CONCAT(a.first_name, ' ', a.last_name)                 AS agent_name,
       a.branch_city,
       a.commission_rate,
       CONCAT(m.first_name, ' ', m.last_name)                 AS manager_name,
       COUNT(DISTINCT p.policy_id)                            AS policies_sold,
       COUNT(DISTINCT CASE WHEN p.status = 'ACTIVE' THEN p.policy_id END) AS active_policies,
       COALESCE(SUM(pp.amount), 0)                            AS premium_collected,
       ROUND(COALESCE(SUM(pp.amount), 0) * a.commission_rate / 100, 2) AS commission_earned
  FROM agent a
  LEFT JOIN agent m  ON m.agent_id = a.manager_id
  LEFT JOIN policy p ON p.agent_id = a.agent_id
  LEFT JOIN premium_payment pp ON pp.policy_id = p.policy_id AND pp.status = 'PAID'
 GROUP BY a.agent_id, a.first_name, a.last_name, a.branch_city, a.commission_rate,
          m.first_name, m.last_name;

-- 4. Monthly claims trend
CREATE OR REPLACE VIEW v_monthly_claims AS
SELECT DATE_FORMAT(cl.filed_on, '%Y-%m-01')                   AS month_start,
       COUNT(*)                                               AS claims_filed,
       SUM(cl.claimed_amount)                                 AS amount_claimed,
       SUM(cl.status IN ('APPROVED', 'PAID'))                 AS approved,
       SUM(cl.status = 'REJECTED')                            AS rejected,
       SUM(cl.status IN ('SUBMITTED', 'UNDER_REVIEW'))        AS open_claims,
       COALESCE(SUM(po.amount), 0)                            AS amount_paid
  FROM claim cl
  LEFT JOIN claim_payout po ON po.claim_id = cl.claim_id
 GROUP BY DATE_FORMAT(cl.filed_on, '%Y-%m-01');

-- 5. Overdue premiums (unpaid and past due)
CREATE OR REPLACE VIEW v_overdue_premiums AS
SELECT pp.payment_id,
       pp.policy_id,
       p.policy_number,
       p.status                                               AS policy_status,
       pt.type_name,
       CONCAT(c.first_name, ' ', c.last_name)                 AS customer_name,
       c.phone,
       c.email,
       pp.instalment_no,
       pp.due_date,
       pp.amount,
       pp.status                                              AS payment_status,
       DATEDIFF(CURRENT_DATE, pp.due_date)                    AS days_overdue
  FROM premium_payment pp
  JOIN policy      p  ON p.policy_id   = pp.policy_id
  JOIN policy_type pt ON pt.type_id    = p.type_id
  JOIN customer    c  ON c.customer_id = p.customer_id
 WHERE pp.status IN ('PENDING', 'FAILED')     -- IN (not <>) so idx_payment_status_due is usable
   AND pp.due_date < CURRENT_DATE
   AND p.status IN ('ACTIVE', 'LAPSED');

-- 6. Loss ratio by product = claims paid / premium collected
CREATE OR REPLACE VIEW v_loss_ratio_by_type AS
SELECT pt.type_id,
       pt.type_name,
       COALESCE(prem.premium_collected, 0)                    AS premium_collected,
       COALESCE(paid.claims_paid, 0)                          AS claims_paid,
       COALESCE(paid.paid_claims, 0)                          AS paid_claims,
       ROUND(100 * COALESCE(paid.claims_paid, 0) / NULLIF(prem.premium_collected, 0), 2) AS loss_ratio_pct
  FROM policy_type pt
  LEFT JOIN (SELECT p.type_id, SUM(pp.amount) AS premium_collected
               FROM premium_payment pp JOIN policy p ON p.policy_id = pp.policy_id
              WHERE pp.status = 'PAID'
              GROUP BY p.type_id) prem ON prem.type_id = pt.type_id
  LEFT JOIN (SELECT p.type_id, SUM(po.amount) AS claims_paid, COUNT(*) AS paid_claims
               FROM claim_payout po
               JOIN claim  cl ON cl.claim_id = po.claim_id
               JOIN policy p  ON p.policy_id = cl.policy_id
              GROUP BY p.type_id) paid ON paid.type_id = pt.type_id;

-- 7. Cash ledger: premiums in (+) and claim payouts out (-), via UNION ALL
CREATE OR REPLACE VIEW v_payment_ledger AS
SELECT pp.paid_on                       AS txn_date,
       'PREMIUM_IN'                     AS txn_type,
       pp.policy_id,
       CONCAT('INST-', pp.payment_id)   AS reference,
       pp.method,
       pp.amount                        AS amount
  FROM premium_payment pp
 WHERE pp.status = 'PAID'
UNION ALL
SELECT DATE(po.paid_on),
       'CLAIM_OUT',
       cl.policy_id,
       po.reference_no,
       po.method,
       -po.amount
  FROM claim_payout po
  JOIN claim cl ON cl.claim_id = po.claim_id;

-- 8. Customer directory: customer with city/state joined back from pincode
CREATE OR REPLACE VIEW v_customer_directory AS
SELECT c.customer_id, c.first_name, c.last_name, c.dob, c.gender, c.email, c.phone,
       c.address_line, c.pincode, pin.city, pin.state, c.created_at
  FROM customer c JOIN pincode pin ON pin.pincode = c.pincode;

-- 9. Provider directory
CREATE OR REPLACE VIEW v_provider_directory AS
SELECT pr.provider_id, pr.name, pr.provider_type, pr.pincode, pin.city, pin.state, pr.phone, pr.is_network
  FROM provider pr JOIN pincode pin ON pin.pincode = pr.pincode;

-- 10. ML features: ONLY information known at filing time.
--    No status, assessment, payout or fraud_flag columns -> no label leakage.
CREATE OR REPLACE VIEW v_claim_features AS
SELECT cl.claim_id,
       cl.claimed_amount,
       ROUND(cl.claimed_amount / p.sum_assured, 4)                        AS claim_ratio,
       DATEDIFF(cl.incident_date, p.start_date)                           AS days_since_start,
       DATEDIFF(p.end_date, cl.incident_date)                             AS days_to_end,
       DATEDIFF(DATE(cl.filed_on), cl.incident_date)                      AS filing_delay,
       TIMESTAMPDIFF(YEAR, c.dob, DATE(cl.filed_on))                      AS customer_age,
       (SELECT COUNT(*) FROM claim c2 JOIN policy p2 ON p2.policy_id = c2.policy_id
         WHERE p2.customer_id = p.customer_id AND c2.filed_on < cl.filed_on) AS prior_claims,
       (SELECT COUNT(*) FROM premium_payment pp
         WHERE pp.policy_id = p.policy_id
           AND pp.due_date < DATE(cl.filed_on)
           AND (pp.paid_on > pp.due_date OR pp.paid_on IS NULL))          AS late_payments,
       (SELECT COUNT(*) FROM claim_document d
         WHERE d.claim_id = cl.claim_id
           AND d.uploaded_on <= DATE_ADD(cl.filed_on, INTERVAL 1 DAY))     AS documents_attached,
       CASE WHEN pr.provider_id IS NOT NULL AND pr.is_network = 0 THEN 1 ELSE 0 END AS non_network_provider,
       cl.claim_type,
       pt.type_name                                                       AS policy_type
  FROM claim cl
  JOIN policy      p  ON p.policy_id   = cl.policy_id
  JOIN policy_type pt ON pt.type_id    = p.type_id
  JOIN customer    c  ON c.customer_id = p.customer_id
  LEFT JOIN provider pr ON pr.provider_id = cl.provider_id;
