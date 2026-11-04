"""pytest setup: rebuild the TEST database (insurance_test) from the same SQL files,
load a small fixture set, and point the API at it before it is imported."""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dbutil import ENV, run_sql  # noqa: E402
from build_db import build  # noqa: E402

TEST_DB = ENV["TEST_DB_NAME"]
os.environ["DB_NAME"] = TEST_DB  # must be set before api.db creates its pool

FIXTURES = """
INSERT INTO policy_type (type_id, type_name, min_sum_assured, max_sum_assured, base_rate_pct, max_term_years) VALUES
 (1, 'Health', 100000, 2500000, 3.8, 1), (2, 'Motor', 200000, 2000000, 2.8, 1), (3, 'Life', 1000000, 10000000, 0.6, 30);
INSERT INTO agent (agent_id, first_name, last_name, email, phone, branch_city, hire_date, commission_rate) VALUES
 (1, 'Test', 'Agent', 'agent@test.example.com', '9000000000', 'Prayagraj', '2020-01-01', 10);
INSERT INTO pincode (pincode, city, state) VALUES
 ('211004', 'Prayagraj', 'Uttar Pradesh'), ('226001', 'Lucknow', 'Uttar Pradesh'), ('208001', 'Kanpur', 'Uttar Pradesh');
INSERT INTO customer (customer_id, first_name, last_name, dob, gender, email, phone, address_line, pincode) VALUES
 (1, 'Asha', 'Test', '1990-06-15', 'F', 'asha@test.example.com', '9000000001', '1 Road', '211004');
INSERT INTO provider (provider_id, name, provider_type, pincode, phone, is_network) VALUES
 (1, 'Test Hospital', 'HOSPITAL', '211004', '9000000002', 1);
INSERT INTO adjuster (adjuster_id, first_name, last_name, email, phone, approval_limit) VALUES
 (1, 'Junior', 'Adj', 'junior@test.example.com', '9000000003', 200000),
 (2, 'Senior', 'Adj', 'senior@test.example.com', '9000000004', 5000000);
"""


@pytest.fixture(scope="session", autouse=True)
def test_database():
    build(TEST_DB, seed=False, quiet=True)
    rc, out = run_sql(FIXTURES, database=TEST_DB)
    assert rc == 0, out
    yield


@pytest.fixture(scope="session")
def client(test_database):
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app)


@pytest.fixture
def make_policy(client):
    """Sell a Health policy (default 5,00,000 cover, started 60 days ago) and pay its first instalment."""
    def _make(sum_assured=500000, start_days_ago=60, type_id=1, freq="ANNUAL", pay_first=True):
        r = client.post("/api/policies", json={
            "customer_id": 1, "type_id": type_id, "agent_id": 1,
            "start_date": str(date.today() - timedelta(days=start_days_ago)),
            "term_months": 12, "sum_assured": sum_assured, "payment_frequency": freq})
        assert r.status_code == 201, r.text
        d = r.json()
        if pay_first:
            pay = client.post(f"/api/payments/{d['payments'][0]['payment_id']}/pay", json={"method": "UPI"})
            assert pay.status_code == 200, pay.text
        return d["policy"]
    return _make


@pytest.fixture
def make_claim(client):
    def _make(policy_id, amount=100000, incident_days_ago=5):
        r = client.post("/api/claims", json={
            "policy_id": policy_id, "provider_id": 1, "claim_type": "HOSPITALISATION",
            "incident_date": str(date.today() - timedelta(days=incident_days_ago)), "claimed_amount": amount})
        assert r.status_code == 201, r.text
        return r.json()["claim"]
    return _make


def assert_db_error(resp, status, fragment):
    assert resp.status_code == status, f"{resp.status_code}: {resp.text}"
    assert fragment in resp.json()["detail"], resp.json()["detail"]
