-- =====================================================================
-- 07_queries.sql  --  SQL showcase: DML, joins, subqueries, aggregation,
-- window functions, CTEs (incl. recursive), set operations, reports.
-- Output saved to docs/outputs/07_queries.txt by scripts/run_demos.py
-- =====================================================================

-- ============================ 1. DML ==================================
-- Everything here is rolled back so the dataset is unchanged.
START TRANSACTION;

-- 1.1 INSERT a customer and read it back (MySQL has no RETURNING)
INSERT INTO customer (first_name, last_name, dob, gender, email, phone, address_line, pincode)
VALUES ('Query', 'Demo', '1995-05-15', 'F', 'query.demo@example.com', '9876543210',
        '12, Civil Lines', '211001');
SELECT customer_id, first_name, last_name, city, state
  FROM v_customer_directory WHERE customer_id = LAST_INSERT_ID();

-- 1.2 UPDATE with a join: raise commission by 1 point for agents whose policies all stayed ACTIVE/EXPIRED
UPDATE agent a
  JOIN (SELECT agent_id FROM policy GROUP BY agent_id
         HAVING SUM(status = 'LAPSED') = 0 AND COUNT(*) >= 90) good ON good.agent_id = a.agent_id
   SET a.commission_rate = LEAST(a.commission_rate + 1, 30);
SELECT ROW_COUNT() AS agents_updated;

-- 1.3 DELETE with a subquery: remove the demo customer
DELETE FROM customer WHERE email = 'query.demo@example.com';
SELECT ROW_COUNT() AS customers_deleted;

ROLLBACK;

-- ============================ 2. JOINS ================================
-- 2.1 INNER JOIN across five tables: latest 10 paid claims
SELECT cl.claim_number, CONCAT(c.first_name, ' ', c.last_name) AS customer, pt.type_name,
       pr.name AS provider, cl.claimed_amount, po.amount AS paid, DATE(po.paid_on) AS paid_on
  FROM claim cl
  JOIN policy p        ON p.policy_id   = cl.policy_id
  JOIN customer c      ON c.customer_id = p.customer_id
  JOIN policy_type pt  ON pt.type_id    = p.type_id
  JOIN claim_payout po ON po.claim_id   = cl.claim_id
  LEFT JOIN provider pr ON pr.provider_id = cl.provider_id
 ORDER BY po.paid_on DESC
 LIMIT 10;

-- 2.2 LEFT JOIN + IS NULL (anti-join): customers who hold no policy
SELECT COUNT(*) AS customers_without_policy
  FROM customer c LEFT JOIN policy p ON p.customer_id = c.customer_id
 WHERE p.policy_id IS NULL;

-- 2.3 SELF JOIN: each agent with their manager
SELECT a.agent_id, CONCAT(a.first_name, ' ', a.last_name) AS agent,
       CONCAT(m.first_name, ' ', m.last_name) AS manager
  FROM agent a LEFT JOIN agent m ON m.agent_id = a.manager_id
 ORDER BY a.manager_id IS NULL DESC, a.manager_id, a.agent_id
 LIMIT 12;

-- 2.4 FULL OUTER JOIN emulation (LEFT JOIN UNION RIGHT JOIN):
--     cities with customers vs cities with providers
--     (city lives in pincode, reached through each table's pincode FK)
SELECT cc.city, cc.customers, pc.providers
  FROM (SELECT city, COUNT(*) AS customers FROM v_customer_directory GROUP BY city) cc
  LEFT JOIN (SELECT city, COUNT(*) AS providers FROM v_provider_directory GROUP BY city) pc ON pc.city = cc.city
UNION
SELECT pc.city, cc.customers, pc.providers
  FROM (SELECT city, COUNT(*) AS customers FROM v_customer_directory GROUP BY city) cc
 RIGHT JOIN (SELECT city, COUNT(*) AS providers FROM v_provider_directory GROUP BY city) pc ON pc.city = cc.city
 ORDER BY city;

-- ============================ 3. SUBQUERIES ===========================
-- 3.1 Scalar subquery: claims larger than the overall average claim
SELECT COUNT(*) AS claims_above_average,
       (SELECT ROUND(AVG(claimed_amount), 2) FROM claim) AS overall_average
  FROM claim WHERE claimed_amount > (SELECT AVG(claimed_amount) FROM claim);

-- 3.2 Correlated subquery: claims more than 3x the average of their own claim type
SELECT cl.claim_number, cl.claim_type, cl.claimed_amount
  FROM claim cl
 WHERE cl.claimed_amount > 3 * (SELECT AVG(c2.claimed_amount) FROM claim c2
                                 WHERE c2.claim_type = cl.claim_type)
 ORDER BY cl.claimed_amount DESC LIMIT 10;

-- 3.3 IN: customers who have at least one rejected claim
SELECT COUNT(*) AS customers_with_rejection
  FROM customer
 WHERE customer_id IN (SELECT p.customer_id FROM policy p JOIN claim cl ON cl.policy_id = p.policy_id
                        WHERE cl.status = 'REJECTED');

-- 3.4 NOT EXISTS: ACTIVE policies that never had a claim
SELECT COUNT(*) AS active_policies_without_claims
  FROM policy p
 WHERE p.status = 'ACTIVE'
   AND NOT EXISTS (SELECT 1 FROM claim cl WHERE cl.policy_id = p.policy_id);

-- 3.5 > ALL: providers whose total paid exceeds every non-network provider's total
SELECT pr.name, SUM(po.amount) AS total_paid
  FROM provider pr JOIN claim cl ON cl.provider_id = pr.provider_id
  JOIN claim_payout po ON po.claim_id = cl.claim_id
 GROUP BY pr.provider_id, pr.name
HAVING SUM(po.amount) > ALL (SELECT SUM(po2.amount)
                               FROM provider pr2 JOIN claim c2 ON c2.provider_id = pr2.provider_id
                               JOIN claim_payout po2 ON po2.claim_id = c2.claim_id
                              WHERE pr2.is_network = 0 GROUP BY pr2.provider_id)
 ORDER BY total_paid DESC;

-- ============================ 4. AGGREGATION ==========================
-- 4.1 GROUP BY + HAVING: claim types with an approval rate below 80%
SELECT claim_type, COUNT(*) AS decided,
       ROUND(100 * SUM(status IN ('APPROVED', 'PAID')) / COUNT(*), 1) AS approval_rate_pct
  FROM claim WHERE status IN ('APPROVED', 'PAID', 'REJECTED')
 GROUP BY claim_type
HAVING approval_rate_pct < 80
 ORDER BY approval_rate_pct;

-- 4.2 WITH ROLLUP + GROUPING(): policies by product and status with subtotals
SELECT IF(GROUPING(pt.type_name), 'ALL PRODUCTS', pt.type_name) AS product,
       IF(GROUPING(p.status), 'all statuses', p.status)          AS status,
       COUNT(*) AS policies, SUM(p.sum_assured) AS total_cover
  FROM policy p JOIN policy_type pt ON pt.type_id = p.type_id
 GROUP BY pt.type_name, p.status WITH ROLLUP;

-- ============================ 5. WINDOW FUNCTIONS =====================
-- 5.1 RANK within partition: top 3 agents by commission per manager team
SELECT * FROM (
    SELECT COALESCE(manager_name, '(managers)') AS team, agent_name, commission_earned,
           RANK() OVER (PARTITION BY manager_name ORDER BY commission_earned DESC) AS rnk
      FROM v_agent_performance) r
 WHERE rnk <= 3 ORDER BY team, rnk;

-- 5.2 Running total and month-over-month change with LAG
SELECT month_start, claims_filed,
       SUM(claims_filed) OVER (ORDER BY month_start)                  AS running_total,
       claims_filed - LAG(claims_filed) OVER (ORDER BY month_start)   AS change_vs_prev,
       ROUND(AVG(claims_filed) OVER (ORDER BY month_start
                                     ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 1) AS moving_avg_3m
  FROM v_monthly_claims
 ORDER BY month_start DESC LIMIT 12;

-- 5.3 NTILE: claim amount quartiles per product and fraud rate in each
SELECT type_name, quartile, COUNT(*) AS claims,
       MIN(claimed_amount) AS from_amt, MAX(claimed_amount) AS to_amt,
       ROUND(100 * AVG(fraud_flag), 1) AS fraud_rate_pct
  FROM (SELECT type_name, claimed_amount, fraud_flag,
               NTILE(4) OVER (PARTITION BY type_name ORDER BY claimed_amount) AS quartile
          FROM v_claim_summary) q
 GROUP BY type_name, quartile ORDER BY type_name, quartile;

-- 5.4 ROW_NUMBER: each customer's most recent claim (first 10)
SELECT customer_name, claim_number, filed_on, status
  FROM (SELECT customer_name, claim_number, filed_on, status,
               ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY filed_on DESC) AS rn
          FROM v_claim_summary) x
 WHERE rn = 1 ORDER BY filed_on DESC LIMIT 10;

-- ============================ 6. CTEs =================================
-- 6.1 Recursive CTE: the full agent hierarchy with depth and path
WITH RECURSIVE org AS (
    SELECT agent_id, manager_id, CONCAT(first_name, ' ', last_name) AS name, 0 AS depth,
           CAST(CONCAT(first_name, ' ', last_name) AS CHAR(500)) AS path
      FROM agent WHERE manager_id IS NULL
    UNION ALL
    SELECT a.agent_id, a.manager_id, CONCAT(a.first_name, ' ', a.last_name), o.depth + 1,
           CONCAT(o.path, ' > ', a.first_name, ' ', a.last_name)
      FROM agent a JOIN org o ON a.manager_id = o.agent_id
)
SELECT agent_id, depth, path FROM org ORDER BY path LIMIT 12;

-- 6.2 Multiple CTEs: top 2 customers by total premium paid in each city
WITH paid AS (
    SELECT p.customer_id, SUM(pp.amount) AS premium_paid
      FROM premium_payment pp JOIN policy p ON p.policy_id = pp.policy_id
     WHERE pp.status = 'PAID' GROUP BY p.customer_id
), ranked AS (
    SELECT pin.city, CONCAT(c.first_name, ' ', c.last_name) AS customer, pd.premium_paid,
           DENSE_RANK() OVER (PARTITION BY pin.city ORDER BY pd.premium_paid DESC) AS rnk
      FROM paid pd
      JOIN customer c  ON c.customer_id = pd.customer_id
      JOIN pincode pin ON pin.pincode   = c.pincode
)
SELECT city, customer, premium_paid FROM ranked WHERE rnk <= 2 ORDER BY city, rnk;

-- 6.3 Recursive CTE as a calendar: claims per month including empty months, last 12 months
WITH RECURSIVE months AS (
    SELECT DATE_FORMAT(DATE_SUB(CURRENT_DATE, INTERVAL 11 MONTH), '%Y-%m-01') AS m
    UNION ALL
    SELECT DATE_FORMAT(DATE_ADD(m, INTERVAL 1 MONTH), '%Y-%m-01') FROM months
     WHERE m < DATE_FORMAT(CURRENT_DATE, '%Y-%m-01')
)
SELECT months.m AS month_start, COALESCE(v.claims_filed, 0) AS claims_filed
  FROM months LEFT JOIN v_monthly_claims v ON v.month_start = months.m
 ORDER BY months.m;

-- ============================ 7. SET OPERATIONS (8.0.31+) =============
-- 7.1 UNION: every e-mail we might contact (customers and agents)
SELECT COUNT(*) AS distinct_contacts FROM (
    SELECT email FROM customer UNION SELECT email FROM agent) u;

-- 7.2 INTERSECT: customers holding BOTH a Health and a Motor policy
SELECT COUNT(*) AS health_and_motor FROM (
    SELECT p.customer_id FROM policy p JOIN policy_type t ON t.type_id = p.type_id WHERE t.type_name = 'Health'
    INTERSECT
    SELECT p.customer_id FROM policy p JOIN policy_type t ON t.type_id = p.type_id WHERE t.type_name = 'Motor') x;

-- 7.3 EXCEPT: Health customers with no Life cover (cross-sell list)
SELECT COUNT(*) AS health_without_life FROM (
    SELECT p.customer_id FROM policy p JOIN policy_type t ON t.type_id = p.type_id WHERE t.type_name = 'Health'
    EXCEPT
    SELECT p.customer_id FROM policy p JOIN policy_type t ON t.type_id = p.type_id WHERE t.type_name = 'Life') x;

-- ============================ 8. REPORTS (F8) =========================
-- R1 monthly claims (last 6 months)
SELECT * FROM v_monthly_claims ORDER BY month_start DESC LIMIT 6;
-- R2 agent commission (top 10)
SELECT agent_name, branch_city, policies_sold, premium_collected, commission_rate, commission_earned
  FROM v_agent_performance ORDER BY commission_earned DESC LIMIT 10;
-- R3 overdue premiums (oldest 10)
SELECT policy_number, customer_name, instalment_no, due_date, amount, days_overdue, policy_status
  FROM v_overdue_premiums ORDER BY days_overdue DESC LIMIT 10;
-- R4 loss ratio by product
SELECT * FROM v_loss_ratio_by_type ORDER BY loss_ratio_pct DESC;
-- R5 policies expiring in the next 30 days
SELECT policy_number, customer_name, type_name, end_date, days_to_expiry
  FROM v_policy_overview
 WHERE status = 'ACTIVE' AND end_date BETWEEN CURRENT_DATE AND DATE_ADD(CURRENT_DATE, INTERVAL 30 DAY)
 ORDER BY end_date LIMIT 10;
-- R6 open claims queue
SELECT claim_number, status, type_name, customer_name, claimed_amount, filed_on, adjuster_name
  FROM v_claim_summary WHERE status IN ('SUBMITTED', 'UNDER_REVIEW') ORDER BY filed_on LIMIT 10;
-- R7 claims by product
SELECT type_name, COUNT(*) AS claims, SUM(claimed_amount) AS claimed,
       SUM(COALESCE(paid_amount, 0)) AS paid, ROUND(AVG(days_to_settle), 1) AS avg_days_to_settle
  FROM v_claim_summary GROUP BY type_name ORDER BY claims DESC;
-- R8 top providers by amount paid
SELECT provider_name, IF(is_network, 'Network', 'Non-network') AS network, COUNT(*) AS claims,
       SUM(COALESCE(paid_amount, 0)) AS paid
  FROM v_claim_summary WHERE provider_id IS NOT NULL
 GROUP BY provider_id, provider_name, is_network ORDER BY paid DESC LIMIT 10;
