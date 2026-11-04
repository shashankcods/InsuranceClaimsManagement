"""F1 generic CRUD: round trips, list options, and constraint errors mapped to HTTP codes."""
from conftest import assert_db_error

NEW_CUSTOMER = {"first_name": "Ravi", "last_name": "Kumar", "dob": "1985-03-02", "gender": "M",
                "email": "ravi.crud@test.example.com", "phone": "9111111111", "address_line": "2 Lane",
                "pincode": "226001"}


def test_customer_round_trip(client):
    r = client.post("/api/customers", json=NEW_CUSTOMER)
    assert r.status_code == 201, r.text
    cid = r.json()["customer_id"]
    got = client.get(f"/api/customers/{cid}").json()
    assert got["email"] == NEW_CUSTOMER["email"] and got["city"] == "Lucknow"   # city joined from pincode

    r = client.put(f"/api/customers/{cid}", json={"pincode": "208001"})
    assert r.status_code == 200 and r.json()["city"] == "Kanpur"

    lst = client.get("/api/customers", params={"search": "ravi.crud", "sort": "city", "order": "desc"}).json()
    assert lst["total"] == 1 and lst["items"][0]["customer_id"] == cid
    assert client.get("/api/customers", params={"city": "Kanpur"}).json()["total"] >= 1

    assert client.delete(f"/api/customers/{cid}").status_code == 200
    assert client.get(f"/api/customers/{cid}").status_code == 404


def test_crud_on_every_resource_lists(client):
    for res in ["pincodes", "customers", "agents", "policy-types", "providers", "adjusters", "nominees",
                "payments", "documents"]:
        r = client.get(f"/api/{res}", params={"limit": 5})
        assert r.status_code == 200, res
        assert "items" in r.json() and "total" in r.json()


def test_pincode_crud_with_string_key(client):
    r = client.post("/api/pincodes", json={"pincode": "221001", "city": "Varanasi", "state": "Uttar Pradesh"})
    assert r.status_code == 201 and r.json()["pincode"] == "221001"
    assert client.put("/api/pincodes/221001", json={"city": "Kashi"}).json()["city"] == "Kashi"
    # changing the key itself returns the row under its new key
    r = client.put("/api/pincodes/221001", json={"pincode": "221002"})
    assert r.status_code == 200 and r.json()["pincode"] == "221002"
    assert client.delete("/api/pincodes/221002").status_code == 200


def test_pincode_change_cascades_to_customers(client):
    client.post("/api/pincodes", json={"pincode": "282001", "city": "Agra", "state": "Uttar Pradesh"})
    cust = client.post("/api/customers", json=dict(NEW_CUSTOMER, email="cascade@test.example.com",
                                                   pincode="282001")).json()
    client.put("/api/pincodes/282001", json={"pincode": "282002"})
    assert client.get(f"/api/customers/{cust['customer_id']}").json()["pincode"] == "282002"   # ON UPDATE CASCADE


def test_check_constraint_is_422(client):
    assert_db_error(client.post("/api/pincodes", json={"pincode": "21A00", "city": "X", "state": "Y"}),
                    422, "ck_pincode_format")


def test_unknown_pincode_is_fk_409(client):
    bad = dict(NEW_CUSTOMER, email="no.pin@test.example.com", pincode="999999")
    assert_db_error(client.post("/api/customers", json=bad), 409, "fk_customer_pincode")


def test_pincode_in_use_cannot_be_deleted(client):
    assert_db_error(client.delete("/api/pincodes/211004"), 409, "foreign key constraint fails")


def test_duplicate_email_is_409(client):
    dup = dict(NEW_CUSTOMER, email="asha@test.example.com")
    assert_db_error(client.post("/api/customers", json=dup), 409, "Duplicate entry")


def test_fk_violation_is_409(client):
    assert_db_error(client.post("/api/documents", json={"claim_id": 999999, "doc_type": "PHOTO", "file_name": "x.jpg"}),
                    409, "foreign key constraint fails")


def test_payments_are_read_only_through_crud(client, make_policy):
    pid = make_policy(pay_first=False)["policy_id"]
    pay = client.get("/api/payments", params={"policy_id": pid}).json()["items"][0]
    assert client.put(f"/api/payments/{pay['payment_id']}", json={"status": "PAID"}).status_code == 405
    assert client.post("/api/payments", json={"policy_id": pid, "instalment_no": 9}).status_code == 405
    assert client.delete(f"/api/payments/{pay['payment_id']}").status_code == 405
    # the dedicated endpoint (sp_pay_premium) still works
    assert client.post(f"/api/payments/{pay['payment_id']}/pay", json={"method": "UPI"}).json()["status"] == "PAID"


def test_whitelist_blocks_unknown_columns_and_sorts(client):
    r = client.post("/api/customers", json=dict(NEW_CUSTOMER, created_at="2020-01-01"))
    assert r.status_code == 422 and "read-only" in r.json()["detail"]
    r = client.post("/api/customers", json=dict(NEW_CUSTOMER, city="Lucknow"))   # city is not a customer column
    assert r.status_code == 422
    r = client.get("/api/customers", params={"sort": "email; DROP TABLE customer"})
    assert r.status_code == 400
    r = client.get("/api/drop-table")
    assert r.status_code == 404


def test_search_value_is_parameterised(client):
    r = client.get("/api/customers", params={"search": "' OR '1'='1"})
    assert r.status_code == 200 and r.json()["total"] == 0
