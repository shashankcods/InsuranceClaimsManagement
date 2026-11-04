"""The 8 reports (F8) plus dashboard KPIs. Each report is one SQL statement over the views."""
REPORTS = {
    "monthly-claims": dict(
        title="Monthly claims",
        sql="""SELECT month_start, claims_filed, amount_claimed, approved, rejected, open_claims, amount_paid,
                      ROUND(100 * approved / NULLIF(approved + rejected, 0), 1) AS approval_rate_pct
                 FROM v_monthly_claims ORDER BY month_start DESC LIMIT 24"""),
    "agent-commission": dict(
        title="Agent commission",
        sql="""SELECT agent_name, branch_city, manager_name, policies_sold, active_policies,
                      premium_collected, commission_rate, commission_earned,
                      RANK() OVER (ORDER BY commission_earned DESC) AS rank_overall
                 FROM v_agent_performance ORDER BY commission_earned DESC"""),
    "overdue-premiums": dict(
        title="Overdue premiums",
        sql="""SELECT policy_number, customer_name, phone, type_name, instalment_no, due_date, amount,
                      days_overdue, policy_status
                 FROM v_overdue_premiums ORDER BY days_overdue DESC"""),
    "loss-ratio": dict(
        title="Loss ratio by product",
        sql="""SELECT type_name, premium_collected, claims_paid, paid_claims, loss_ratio_pct
                 FROM v_loss_ratio_by_type ORDER BY loss_ratio_pct DESC"""),
    "expiring-policies": dict(
        title="Policies expiring in the next 60 days",
        sql="""SELECT policy_number, customer_name, type_name, agent_name, end_date, days_to_expiry,
                      sum_assured, premium_amount
                 FROM v_policy_overview
                WHERE status = 'ACTIVE' AND end_date BETWEEN CURRENT_DATE AND DATE_ADD(CURRENT_DATE, INTERVAL 60 DAY)
                ORDER BY end_date"""),
    "open-claims": dict(
        title="Open claims by risk",
        sql="""SELECT claim_number, status, type_name, customer_name, claimed_amount, filed_on,
                      DATEDIFF(CURRENT_DATE, filed_on) AS days_open, adjuster_name, fraud_score, risk_band
                 FROM v_claim_summary WHERE status IN ('SUBMITTED', 'UNDER_REVIEW')
                ORDER BY fraud_score IS NULL, fraud_score DESC, filed_on"""),
    "claims-by-product": dict(
        title="Claims by product",
        sql="""SELECT type_name, COUNT(*) AS claims, SUM(claimed_amount) AS claimed,
                      SUM(COALESCE(paid_amount, 0)) AS paid, SUM(status = 'REJECTED') AS rejected,
                      ROUND(AVG(days_to_settle), 1) AS avg_days_to_settle,
                      ROUND(100 * AVG(fraud_flag), 1) AS confirmed_fraud_pct
                 FROM v_claim_summary GROUP BY type_name ORDER BY claims DESC"""),
    "top-providers": dict(
        title="Top providers by amount paid",
        sql="""SELECT provider_name, IF(is_network, 'Network', 'Non-network') AS network, COUNT(*) AS claims,
                      SUM(COALESCE(paid_amount, 0)) AS paid, ROUND(100 * AVG(fraud_flag), 1) AS confirmed_fraud_pct
                 FROM v_claim_summary WHERE provider_id IS NOT NULL
                GROUP BY provider_id, provider_name, is_network ORDER BY paid DESC LIMIT 20"""),
}

DASHBOARD_SQL = """
SELECT (SELECT COUNT(*) FROM policy WHERE status = 'ACTIVE')                         AS active_policies,
       (SELECT COUNT(*) FROM policy WHERE status = 'LAPSED')                         AS lapsed_policies,
       (SELECT COUNT(*) FROM customer)                                               AS customers,
       (SELECT COUNT(*) FROM claim WHERE status IN ('SUBMITTED', 'UNDER_REVIEW'))    AS open_claims,
       (SELECT COUNT(*) FROM v_claim_summary WHERE status IN ('SUBMITTED', 'UNDER_REVIEW')
                                               AND risk_band = 'HIGH')               AS high_risk_open,
       (SELECT COALESCE(SUM(amount), 0) FROM premium_payment
         WHERE status = 'PAID' AND paid_on >= DATE_SUB(CURRENT_DATE, INTERVAL 12 MONTH)) AS premium_12m,
       (SELECT COALESCE(SUM(amount), 0) FROM claim_payout
         WHERE paid_on >= DATE_SUB(CURRENT_DATE, INTERVAL 12 MONTH))                 AS payouts_12m,
       (SELECT COUNT(*) FROM v_overdue_premiums)                                     AS overdue_instalments,
       (SELECT COALESCE(SUM(amount), 0) FROM v_overdue_premiums)                     AS overdue_amount
"""
