"""Atomicity, concurrency, reports and ML scoring."""
import threading

from conftest import assert_db_error


def test_failed_approve_and_pay_leaves_no_partial_state(client, make_policy, make_claim):
    p = make_policy(sum_assured=500000)
    c1 = make_claim(p["policy_id"], amount=400000)
    client.post(f"/api/claims/{c1['claim_id']}/start-review", json={"adjuster_id": 2})
    assert client.post(f"/api/claims/{c1['claim_id']}/approve-and-pay",
                       json={"adjuster_id": 2, "amount": 400000}).status_code == 200

    c2 = make_claim(p["policy_id"], amount=200000)
    client.post(f"/api/claims/{c2['claim_id']}/start-review", json={"adjuster_id": 2})
    assert_db_error(client.post(f"/api/claims/{c2['claim_id']}/approve-and-pay",
                                json={"adjuster_id": 2, "amount": 200000}), 409, "BR6")
    d = client.get(f"/api/claims/{c2['claim_id']}/detail").json()
    assert d["claim"]["status"] == "UNDER_REVIEW"     # status change rolled back
    assert d["assessments"] == []                       # assessment insert rolled back
    assert d["payout"] is None
    assert [x["new_status"] for x in d["status_log"]] == ["SUBMITTED", "UNDER_REVIEW"]  # no audit row either


def test_concurrent_approval_only_one_wins(client, make_policy, make_claim):
    c = make_claim(make_policy()["policy_id"], amount=50000)
    client.post(f"/api/claims/{c['claim_id']}/start-review", json={"adjuster_id": 2})
    results = []

    def approve():
        r = client.post(f"/api/claims/{c['claim_id']}/approve", json={"adjuster_id": 2, "amount": 50000})
        results.append(r.status_code)

    threads = [threading.Thread(target=approve) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [200, 409, 409, 409]
    d = client.get(f"/api/claims/{c['claim_id']}/detail").json()
    assert len([a for a in d["assessments"] if a["decision"] == "APPROVED"]) == 1


def test_reports_return_rows_and_csv(client, make_policy, make_claim):
    c = make_claim(make_policy()["policy_id"], amount=20000)
    for rep in client.get("/api/reports").json():
        r = client.get(f"/api/reports/{rep['name']}")
        assert r.status_code == 200, rep
        assert isinstance(r.json()["rows"], list)
    assert client.get("/api/reports/open-claims").json()["rows"]
    csv = client.get("/api/reports/loss-ratio", params={"format": "csv"})
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert csv.text.splitlines()[0].startswith("type_name")
    assert client.get("/api/reports/dashboard").json()["kpis"]["open_claims"] >= 1
    assert client.get("/api/reports/nope").status_code == 404


def test_fraud_scoring_writes_score(client, make_policy, make_claim):
    from ml import fraud
    c = make_claim(make_policy()["policy_id"], amount=30000)
    r = client.post(f"/api/claims/{c['claim_id']}/fraud-score")
    if fraud.load_bundle() is None:
        assert r.status_code == 503
        return
    assert r.status_code == 200
    s = r.json()["fraud_score"]
    assert 0 <= s <= 1 and r.json()["risk_band"] in ("LOW", "MEDIUM", "HIGH")
    assert client.get(f"/api/claims/{c['claim_id']}/detail").json()["claim"]["fraud_score"] == s
    bulk = client.post("/api/fraud/score-open").json()
    assert bulk["scored"] >= 1


def test_attaching_a_document_rescores_open_claim(client, make_policy, make_claim):
    from ml import fraud
    if fraud.load_bundle() is None:
        return
    c = make_claim(make_policy()["policy_id"], amount=30000)
    before = client.get(f"/api/claims/{c['claim_id']}/detail").json()
    assert before["features"]["documents_attached"] == 0
    for t in ["CLAIM_FORM", "MEDICAL_BILL", "DISCHARGE_SUMMARY", "ID_PROOF"]:
        assert client.post("/api/documents", json={"claim_id": c["claim_id"], "doc_type": t,
                                                   "file_name": f"{t.lower()}.pdf"}).status_code == 201
    after = client.get(f"/api/claims/{c['claim_id']}/detail").json()
    assert after["features"]["documents_attached"] == 4
    # the stored score was recomputed with the new feature value
    from api.db import query
    expected = fraud.score_rows(query("SELECT * FROM v_claim_features WHERE claim_id = %s", (c["claim_id"],)))
    assert float(after["claim"]["fraud_score"]) == expected[c["claim_id"]]


def test_risk_bands_follow_registered_threshold(client, make_policy, make_claim):
    from api.db import callproc, execute, query_one
    c = make_claim(make_policy()["policy_id"], amount=25000)
    execute("UPDATE claim SET fraud_score = 0.40 WHERE claim_id = %s", (c["claim_id"],))
    band = lambda: query_one("SELECT risk_band FROM v_claim_summary WHERE claim_id = %s", (c["claim_id"],))["risk_band"]
    callproc("sp_register_model", ("test model A", 0.70, 0.9, 100, 0))
    assert band() == "MEDIUM"        # 0.40 >= 0.70 / 2
    callproc("sp_register_model", ("test model B", 0.35, 0.9, 100, 0))
    assert band() == "HIGH"          # 0.40 >= 0.35
    assert query_one("SELECT SUM(is_active) AS n FROM fraud_model")["n"] == 1   # exactly one active model
