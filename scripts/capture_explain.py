"""Capture real EXPLAIN ANALYZE output before and after the 06_indexes.sql indexes.

Drops the secondary indexes, measures, recreates them, measures again.
Output: docs/outputs/explain_before_after.txt  (never hand-write timings)
"""
from dbutil import DB_DIR, ENV, OUT_DIR, run_file, run_sql

DB = ENV["DB_NAME"]
QUERIES = {
    "Q1 open-claims queue":
        "SELECT claim_id, claim_number, filed_on FROM claim "
        "WHERE status IN ('SUBMITTED','UNDER_REVIEW') ORDER BY filed_on LIMIT 50",
    "Q2 overdue premiums":
        "SELECT payment_id, policy_id, due_date, amount FROM premium_payment "
        "WHERE status IN ('PENDING','FAILED') AND due_date < CURRENT_DATE",
    "Q3 policies expiring in 30 days":
        "SELECT policy_id, end_date FROM policy WHERE status = 'ACTIVE' "
        "AND end_date BETWEEN CURRENT_DATE AND DATE_ADD(CURRENT_DATE, INTERVAL 30 DAY)",
    "Q4 customers in a city":
        "SELECT c.customer_id, c.first_name, c.last_name FROM pincode p "
        "JOIN customer c ON c.pincode = p.pincode WHERE p.city = 'Lucknow'",
}
DROP = """
DROP INDEX idx_policy_status_end  ON policy;
DROP INDEX idx_claim_status_filed ON claim;
DROP INDEX idx_claim_filed        ON claim;
DROP INDEX idx_payment_status_due ON premium_payment;
DROP INDEX idx_pincode_city       ON pincode;
DROP INDEX idx_customer_name      ON customer;
"""


def measure(label):
    sql = "ANALYZE TABLE policy, claim, premium_payment, customer, pincode;\n"
    for name, q in QUERIES.items():
        sql += f"SELECT '{label}: {name}' AS query;\nEXPLAIN ANALYZE {q};\n"
    rc, out = run_sql(sql, database=DB, table=False)
    if rc != 0:
        raise SystemExit(out)
    return out.replace("\\n", "\n")


run_sql(DROP, database=DB, force=True)
before = measure("BEFORE")
rc, out = run_file(DB_DIR / "06_indexes.sql", database=DB, force=True)  # idx_document_claim is never dropped
after = measure("AFTER")

OUT_DIR.mkdir(parents=True, exist_ok=True)
target = OUT_DIR / "explain_before_after.txt"
target.write_text("=== WITHOUT secondary indexes ===\n" + before +
                  "\n\n=== WITH indexes from 06_indexes.sql ===\n" + after, encoding="utf-8")
print(target.read_text(encoding="utf-8"))
