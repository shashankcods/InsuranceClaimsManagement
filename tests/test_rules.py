"""BR1-BR10 each return the expected error (or effect), through the API."""
from datetime import date, timedelta

from conftest import assert_db_error


def test_policy_sale_validates_cover(client, make_policy):
    p = make_policy()
    assert p["status"] == "ACTIVE" and p["policy_number"].startswith("POL-")
    r = client.post("/api/policies", json={"customer_id": 1, "type_id": 1, "start_date": str(date.today()),
                                           "term_months": 12, "sum_assured": 99000000})
    assert_db_error(r, 409, "outside the product range")


def test_br1_no_claim_on_lapsed_or_cancelled(client, make_policy, make_claim):
    p = make_policy(start_days_ago=200, freq="QUARTERLY", type_id=2, sum_assured=600000, pay_first=False)
    client.post("/api/admin/generate-instalments")
    client.post("/api/admin/lapse-overdue", json={"grace_days": 30})
    assert client.get(f"/api/policies/{p['policy_id']}/detail").json()["policy"]["status"] == "LAPSED"
    r = client.post("/api/claims", json={"policy_id": p["policy_id"], "claim_type": "VEHICLE_DAMAGE",
                                         "incident_date": str(date.today() - timedelta(days=3)), "claimed_amount": 1000})
    assert_db_error(r, 409, "BR1")


def test_br2_incident_outside_period(client, make_policy):
    p = make_policy()
    r = client.post("/api/claims", json={"policy_id": p["policy_id"], "claim_type": "OUTPATIENT",
                                         "incident_date": str(date.today() - timedelta(days=400)), "claimed_amount": 1000})
    assert_db_error(r, 409, "BR2")


def test_br3_amount_above_sum_assured(client, make_policy):
    p = make_policy(sum_assured=500000)
    r = client.post("/api/claims", json={"policy_id": p["policy_id"], "claim_type": "OUTPATIENT",
                                         "incident_date": str(date.today() - timedelta(days=2)), "claimed_amount": 600000})
    assert_db_error(r, 409, "BR3")


def test_br4_illegal_transitions(client, make_policy, make_claim):
    c = make_claim(make_policy()["policy_id"])
    # approving a SUBMITTED claim skips review
    assert_db_error(client.post(f"/api/claims/{c['claim_id']}/approve", json={"adjuster_id": 2, "amount": 1000}),
                    409, "expected UNDER_REVIEW")
    # paying before approval
    assert_db_error(client.post(f"/api/claims/{c['claim_id']}/pay", json={}), 409, "expected APPROVED")
    # the trigger itself blocks a raw status jump (bypassing the procedures)
    from api.db import execute
    import mysql.connector
    try:
        execute("UPDATE claim SET status = 'PAID' WHERE claim_id = %s", (c["claim_id"],))
        raise AssertionError("trigger did not fire")
    except mysql.connector.Error as e:
        assert e.errno == 1644 and "BR4" in e.msg


def test_br5_adjuster_limit_and_claimed_amount(client, make_policy, make_claim):
    c = make_claim(make_policy()["policy_id"], amount=300000)
    client.post(f"/api/claims/{c['claim_id']}/start-review", json={"adjuster_id": 1})
    assert_db_error(client.post(f"/api/claims/{c['claim_id']}/approve", json={"adjuster_id": 1, "amount": 250000}),
                    409, "approval limit")
    assert_db_error(client.post(f"/api/claims/{c['claim_id']}/approve", json={"adjuster_id": 2, "amount": 350000}),
                    409, "exceeds the claimed amount")


def test_br6_policy_cap_and_br7_paid(client, make_policy, make_claim):
    p = make_policy(sum_assured=500000)
    c1 = make_claim(p["policy_id"], amount=300000)
    client.post(f"/api/claims/{c1['claim_id']}/start-review", json={"adjuster_id": 2})
    r = client.post(f"/api/claims/{c1['claim_id']}/approve-and-pay", json={"adjuster_id": 2, "amount": 300000})
    assert r.status_code == 200 and r.json()["claim"]["status"] == "PAID"          # BR7
    assert r.json()["payout"]["amount"] == 300000

    c2 = make_claim(p["policy_id"], amount=300000)
    client.post(f"/api/claims/{c2['claim_id']}/start-review", json={"adjuster_id": 2})
    assert_db_error(client.post(f"/api/claims/{c2['claim_id']}/approve-and-pay",
                                json={"adjuster_id": 2, "amount": 300000}), 409, "BR6")


def test_br8_nominee_share_cap(client, make_policy):
    pid = make_policy()["policy_id"]
    ok = client.post("/api/nominees", json={"policy_id": pid, "full_name": "A", "relationship": "SPOUSE", "share_pct": 60})
    assert ok.status_code == 201
    assert_db_error(client.post("/api/nominees", json={"policy_id": pid, "full_name": "B", "relationship": "SON",
                                                       "share_pct": 50}), 409, "BR8")
    assert_db_error(client.put(f"/api/nominees/{ok.json()['nominee_id']}", json={"share_pct": 101}), 422, "ck_nominee_share")


def test_br9_paying_overdue_reactivates(client, make_policy):
    p = make_policy(start_days_ago=200, freq="QUARTERLY", type_id=2, sum_assured=600000, pay_first=False)
    client.post("/api/admin/generate-instalments")
    client.post("/api/admin/lapse-overdue", json={"grace_days": 30})
    detail = client.get(f"/api/policies/{p['policy_id']}/detail").json()
    assert detail["policy"]["status"] == "LAPSED"
    overdue = [x for x in detail["payments"] if x["is_overdue"]]
    assert len(overdue) >= 2
    statuses = [client.post(f"/api/payments/{x['payment_id']}/pay", json={"method": "UPI"}).json()["policy_status"]
                for x in overdue]
    assert statuses[:-1] == ["LAPSED"] * (len(overdue) - 1) and statuses[-1] == "ACTIVE"


def test_br10_audit_trail(client, make_policy, make_claim):
    c = make_claim(make_policy()["policy_id"], amount=50000)
    client.post(f"/api/claims/{c['claim_id']}/start-review", json={"adjuster_id": 1})
    client.post(f"/api/claims/{c['claim_id']}/reject", json={"adjuster_id": 1, "remarks": "not covered"})
    log = client.get(f"/api/claims/{c['claim_id']}/detail").json()["status_log"]
    assert [(x["old_status"], x["new_status"]) for x in log] == [
        (None, "SUBMITTED"), ("SUBMITTED", "UNDER_REVIEW"), ("UNDER_REVIEW", "REJECTED")]


def test_request_info_keeps_claim_under_review(client, make_policy, make_claim):
    c = make_claim(make_policy()["policy_id"], amount=40000)
    assert_db_error(client.post(f"/api/claims/{c['claim_id']}/request-info", json={"adjuster_id": 1}),
                    409, "expected UNDER_REVIEW")
    client.post(f"/api/claims/{c['claim_id']}/start-review", json={"adjuster_id": 1})
    d = client.post(f"/api/claims/{c['claim_id']}/request-info",
                    json={"adjuster_id": 1, "remarks": "upload bill"}).json()
    assert d["claim"]["status"] == "UNDER_REVIEW"
    assert [(a["decision"], a["remarks"]) for a in d["assessments"]] == [("NEEDS_INFO", "upload bill")]
    # the claim can still be decided afterwards
    r = client.post(f"/api/claims/{c['claim_id']}/approve", json={"adjuster_id": 1, "amount": 40000})
    assert r.json()["claim"]["status"] == "APPROVED"


def test_flag_fraud_after_payment(client, make_policy, make_claim):
    c = make_claim(make_policy()["policy_id"], amount=20000)
    client.post(f"/api/claims/{c['claim_id']}/start-review", json={"adjuster_id": 2})
    client.post(f"/api/claims/{c['claim_id']}/approve-and-pay", json={"adjuster_id": 2, "amount": 20000})
    d = client.post(f"/api/claims/{c['claim_id']}/flag-fraud", json={"fraud_flag": True}).json()
    assert d["claim"]["status"] == "PAID" and d["claim"]["fraud_flag"] == 1
    d = client.post(f"/api/claims/{c['claim_id']}/flag-fraud", json={"fraud_flag": False}).json()
    assert d["claim"]["fraud_flag"] == 0
