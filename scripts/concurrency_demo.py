"""Two-session demos of InnoDB locking (design doc 6.5).

Demo A - concurrent approval: session 1 locks a claim with SELECT ... FOR UPDATE
         inside sp_approve_claim; session 2 calls the same procedure, BLOCKS on the
         row lock, and once session 1 commits it sees status APPROVED and fails.
Demo B - deadlock: two sessions lock two claims in opposite order; InnoDB detects
         the cycle and aborts one with error 1213, the other succeeds.

Output: docs/outputs/concurrency_demo.txt
"""
import threading
import time
from datetime import date, timedelta

import mysql.connector

from dbutil import ENV, OUT_DIR

LOG = []
T0 = time.time()


def log(who, msg):
    line = f"[{time.time() - T0:6.2f}s] {who:10s} {msg}"
    LOG.append(line)
    print(line)


def connect():
    return mysql.connector.connect(host=ENV["DB_HOST"], port=int(ENV["DB_PORT"]), user=ENV["DB_USER"],
                                   password=ENV["DB_PASSWORD"], database=ENV["DB_NAME"], autocommit=True)


def setup_claims(n):
    """File n fresh claims on an active policy and move them to UNDER_REVIEW."""
    c = connect()
    cur = c.cursor()
    cur.execute("""SELECT p.policy_id FROM policy p
                    WHERE p.status = 'ACTIVE' AND p.type_id = 1 AND p.sum_assured >= 1000000
                      AND p.start_date <= CURRENT_DATE - INTERVAL 5 DAY AND p.end_date >= CURRENT_DATE
                      AND NOT EXISTS (SELECT 1 FROM claim c WHERE c.policy_id = p.policy_id)
                    ORDER BY p.policy_id LIMIT 1""")
    (policy_id,) = cur.fetchone()
    ids = []
    for _ in range(n):
        incident = date.today() - timedelta(days=2)
        res = cur.callproc("sp_file_claim", (policy_id, 1, "OUTPATIENT", incident, 5000, "concurrency demo", 0, ""))
        ids.append(res[6])
        cur.callproc("sp_start_review", (res[6], 14))
    c.close()
    return ids


def demo_concurrent_approval(claim_id):
    log("setup", f"--- Demo A: two sessions approve claim {claim_id} at the same time ---")
    s1, s2 = connect(), connect()
    s1.autocommit = False
    c1 = s1.cursor()
    # Session 1 runs the approval steps by hand so we can hold the lock open.
    s1.start_transaction()
    c1.execute("SELECT status FROM claim WHERE claim_id = %s FOR UPDATE", (claim_id,))
    log("session1", f"locked claim, status = {c1.fetchone()[0]}")
    c1.execute("INSERT INTO claim_assessment (claim_id, adjuster_id, decision, approved_amount, remarks) "
               "VALUES (%s, 14, 'APPROVED', 5000, 'session 1')", (claim_id,))
    c1.execute("UPDATE claim SET status = 'APPROVED' WHERE claim_id = %s", (claim_id,))
    log("session1", "approved inside the open transaction (not committed yet)")

    def second():
        cur = s2.cursor()
        log("session2", "CALL sp_approve_claim(...) -> waits for the row lock")
        t = time.time()
        try:
            cur.callproc("sp_approve_claim", (claim_id, 15, 5000, "session 2"))
            log("session2", "approved (unexpected)")
        except mysql.connector.Error as e:
            log("session2", f"blocked {time.time() - t:.2f}s, then failed: errno {e.errno}: {e.msg}")

    th = threading.Thread(target=second)
    th.start()
    time.sleep(2)
    s1.commit()
    log("session1", "COMMIT (lock released)")
    th.join()
    cur = s2.cursor()
    cur.execute("SELECT COUNT(*) FROM claim_assessment WHERE claim_id = %s AND decision = 'APPROVED'", (claim_id,))
    log("check", f"APPROVED assessments on the claim: {cur.fetchone()[0]} (exactly one)")
    s1.close()
    s2.close()


def demo_deadlock(a, b):
    log("setup", f"--- Demo B: deadlock on claims {a} and {b} ---")
    s1, s2 = connect(), connect()
    s1.autocommit = s2.autocommit = False
    barrier = threading.Barrier(2)

    def worker(conn, name, first, second):
        cur = conn.cursor()
        try:
            conn.start_transaction()
            cur.execute("SELECT status FROM claim WHERE claim_id = %s FOR UPDATE", (first,))
            cur.fetchall()
            log(name, f"locked claim {first}")
            barrier.wait()
            time.sleep(0.5)
            log(name, f"requesting lock on claim {second}")
            cur.execute("SELECT status FROM claim WHERE claim_id = %s FOR UPDATE", (second,))
            cur.fetchall()
            conn.commit()
            log(name, "got both locks, COMMIT")
        except mysql.connector.Error as e:
            conn.rollback()
            log(name, f"ROLLED BACK by InnoDB: errno {e.errno}: {e.msg}")

    t1 = threading.Thread(target=worker, args=(s1, "session1", a, b))
    t2 = threading.Thread(target=worker, args=(s2, "session2", b, a))
    t1.start(); t2.start(); t1.join(); t2.join()
    s1.close(); s2.close()


def cleanup(ids):
    """Remove the demo claims (cascades to assessments and audit rows) so they never reach reports or ML."""
    c = connect()
    cur = c.cursor()
    cur.execute(f"DELETE FROM claim WHERE claim_id IN ({', '.join(['%s'] * len(ids))})", ids)
    log("cleanup", f"removed {cur.rowcount} demo claims")
    c.close()


if __name__ == "__main__":
    ids = setup_claims(3)
    try:
        demo_concurrent_approval(ids[0])
        demo_deadlock(ids[1], ids[2])
    finally:
        cleanup(ids)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "concurrency_demo.txt").write_text("\n".join(LOG) + "\n", encoding="utf-8")
