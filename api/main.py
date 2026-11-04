"""FastAPI app: thin layer over the database. Business rules live in triggers and
procedures (D10); the API validates shapes, calls procedures and maps errors.

Run:  uvicorn api.main:app --reload      (from the project root)
Docs: http://127.0.0.1:8000/docs
"""
import csv
import io
from datetime import date
from decimal import Decimal
from typing import Optional

import mysql.connector
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ml import fraud

from . import crud
from .db import ROOT, callproc, connection, execute, http_status_for, query, query_one
from .reports import DASHBOARD_SQL, REPORTS

app = FastAPI(title="Insurance & Claims Management API",
              description="DBMS course project, MNNIT Allahabad. Rules are enforced by MySQL triggers/procedures.",
              version="1.0")


@app.exception_handler(mysql.connector.Error)
async def mysql_error_handler(request: Request, exc: mysql.connector.Error):
    """Surface the database's own message (e.g. 'BR3: claimed amount ... exceeds ...')."""
    return JSONResponse(status_code=http_status_for(exc),
                        content={"detail": exc.msg, "errno": exc.errno, "sqlstate": exc.sqlstate})


# ============================ request models ============================
class PolicySale(BaseModel):
    customer_id: int
    type_id: int
    agent_id: Optional[int] = None
    start_date: date
    term_months: int = Field(12, ge=1, le=480)
    sum_assured: Decimal = Field(gt=0)
    payment_frequency: str = "ANNUAL"


class ClaimIn(BaseModel):
    policy_id: int
    provider_id: Optional[int] = None
    claim_type: str
    incident_date: date
    claimed_amount: Decimal = Field(gt=0)
    description: Optional[str] = None


class ReviewIn(BaseModel):
    adjuster_id: int


class ApproveIn(BaseModel):
    adjuster_id: int
    amount: Decimal = Field(gt=0)
    remarks: Optional[str] = None


class PayIn(BaseModel):
    method: str = "NEFT"


class ApprovePayIn(ApproveIn):
    method: str = "NEFT"


class RejectIn(BaseModel):
    adjuster_id: int
    remarks: Optional[str] = None
    is_fraud: bool = False


class FlagIn(BaseModel):
    fraud_flag: bool = True


class PremiumPayIn(BaseModel):
    method: str = "UPI"


class GraceIn(BaseModel):
    grace_days: int = Field(30, ge=0, le=365)


# ============================ lookups ============================
@app.get("/api/meta", tags=["lookups"])
def meta():
    """Small lookup lists for the front-end forms."""
    return {
        "policy_types": query("SELECT type_id, type_name, min_sum_assured, max_sum_assured, base_rate_pct, max_term_years FROM policy_type ORDER BY type_id"),
        "agents": query("SELECT agent_id, CONCAT(first_name, ' ', last_name) AS name FROM agent ORDER BY first_name"),
        "adjusters": query("SELECT adjuster_id, CONCAT(first_name, ' ', last_name) AS name, approval_limit FROM adjuster ORDER BY approval_limit, adjuster_id"),
        "providers": query("SELECT provider_id, name, provider_type, is_network FROM provider ORDER BY name"),
        "claim_types": ["HOSPITALISATION", "OUTPATIENT", "ACCIDENT", "THEFT", "VEHICLE_DAMAGE", "DEATH",
                        "CRITICAL_ILLNESS", "FIRE", "FLOOD", "BURGLARY", "TRIP_CANCELLATION",
                        "BAGGAGE_LOSS", "MEDICAL_EMERGENCY"],
        "doc_types": ["CLAIM_FORM", "MEDICAL_BILL", "DISCHARGE_SUMMARY", "FIR", "PHOTO", "REPAIR_ESTIMATE",
                      "DEATH_CERTIFICATE", "ID_PROOF", "INVOICE", "OTHER"],
        "frequencies": ["SINGLE", "ANNUAL", "HALF_YEARLY", "QUARTERLY", "MONTHLY"],
    }


# ============================ policies ============================
@app.get("/api/policies", tags=["policies"])
def list_policies(request: Request):
    return crud.list_view("policies", dict(request.query_params))


@app.post("/api/policies", tags=["policies"], status_code=201)
def sell_policy(body: PolicySale):
    res = callproc("sp_sell_policy", (body.customer_id, body.type_id, body.agent_id, body.start_date,
                                      body.term_months, body.sum_assured, body.payment_frequency, 0, ""))
    return policy_detail(res[7])


@app.get("/api/policies/{policy_id}/detail", tags=["policies"])
def policy_detail(policy_id: int):
    pol = query_one("SELECT * FROM v_policy_overview WHERE policy_id = %s", (policy_id,))
    if not pol:
        raise HTTPException(404, f"Policy {policy_id} not found")
    return {
        "policy": pol,
        "nominees": query("SELECT * FROM nominee WHERE policy_id = %s ORDER BY nominee_id", (policy_id,)),
        "payments": query("SELECT *, (status <> 'PAID' AND due_date < CURRENT_DATE) AS is_overdue "
                          "FROM premium_payment WHERE policy_id = %s ORDER BY instalment_no", (policy_id,)),
        "claims": query("SELECT claim_id, claim_number, claim_type, filed_on, claimed_amount, status, "
                        "paid_amount, risk_band FROM v_claim_summary WHERE policy_id = %s ORDER BY filed_on",
                        (policy_id,)),
    }


# ============================ claims ============================
@app.get("/api/claims", tags=["claims"])
def list_claims(request: Request):
    return crud.list_view("claims", dict(request.query_params))


@app.post("/api/claims", tags=["claims"], status_code=201)
def file_claim(body: ClaimIn):
    res = callproc("sp_file_claim", (body.policy_id, body.provider_id, body.claim_type, body.incident_date,
                                     body.claimed_amount, body.description, 0, ""))
    claim_id = res[6]
    _score([claim_id])  # score at filing time if a model exists
    return claim_detail(claim_id)


@app.get("/api/claims/{claim_id}/detail", tags=["claims"])
def claim_detail(claim_id: int):
    c = query_one("SELECT * FROM v_claim_summary WHERE claim_id = %s", (claim_id,))
    if not c:
        raise HTTPException(404, f"Claim {claim_id} not found")
    return {
        "claim": c,
        "documents": query("SELECT * FROM claim_document WHERE claim_id = %s ORDER BY doc_id", (claim_id,)),
        "assessments": query("SELECT a.*, CONCAT(ad.first_name, ' ', ad.last_name) AS adjuster_name "
                             "FROM claim_assessment a JOIN adjuster ad ON ad.adjuster_id = a.adjuster_id "
                             "WHERE a.claim_id = %s ORDER BY a.assessed_on, a.assessment_id", (claim_id,)),
        "status_log": query("SELECT * FROM claim_status_log WHERE claim_id = %s ORDER BY changed_at, log_id",
                            (claim_id,)),
        "payout": query_one("SELECT * FROM claim_payout WHERE claim_id = %s", (claim_id,)),
        "features": query_one("SELECT * FROM v_claim_features WHERE claim_id = %s", (claim_id,)),
    }


@app.post("/api/claims/{claim_id}/start-review", tags=["claims"])
def start_review(claim_id: int, body: ReviewIn):
    callproc("sp_start_review", (claim_id, body.adjuster_id))
    return claim_detail(claim_id)


@app.post("/api/claims/{claim_id}/approve", tags=["claims"])
def approve(claim_id: int, body: ApproveIn):
    callproc("sp_approve_claim", (claim_id, body.adjuster_id, body.amount, body.remarks))
    return claim_detail(claim_id)


@app.post("/api/claims/{claim_id}/pay", tags=["claims"])
def pay(claim_id: int, body: PayIn = Body(default=PayIn())):
    callproc("sp_pay_claim", (claim_id, body.method, 0, ""))
    return claim_detail(claim_id)


@app.post("/api/claims/{claim_id}/approve-and-pay", tags=["claims"])
def approve_and_pay(claim_id: int, body: ApprovePayIn):
    """F6: one atomic transaction inside sp_approve_and_pay_claim."""
    callproc("sp_approve_and_pay_claim", (claim_id, body.adjuster_id, body.amount, body.remarks,
                                          body.method, 0, ""))
    return claim_detail(claim_id)


class InfoIn(BaseModel):
    adjuster_id: int
    remarks: Optional[str] = None


@app.post("/api/claims/{claim_id}/request-info", tags=["claims"])
def request_info(claim_id: int, body: InfoIn):
    """Record a NEEDS_INFO assessment; the claim stays UNDER_REVIEW."""
    callproc("sp_request_info", (claim_id, body.adjuster_id, body.remarks))
    return claim_detail(claim_id)


@app.post("/api/claims/{claim_id}/reject", tags=["claims"])
def reject(claim_id: int, body: RejectIn):
    callproc("sp_reject_claim", (claim_id, body.adjuster_id, body.remarks, int(body.is_fraud)))
    return claim_detail(claim_id)


@app.post("/api/claims/{claim_id}/flag-fraud", tags=["claims"])
def flag_fraud(claim_id: int, body: FlagIn = Body(default=FlagIn())):
    n, _ = execute("UPDATE claim SET fraud_flag = %s WHERE claim_id = %s", (int(body.fraud_flag), claim_id))
    if n == 0 and not query_one("SELECT 1 AS x FROM claim WHERE claim_id = %s", (claim_id,)):
        raise HTTPException(404, f"Claim {claim_id} not found")
    return claim_detail(claim_id)


@app.post("/api/claims/{claim_id}/fraud-score", tags=["claims", "ml"])
def fraud_score(claim_id: int):
    scores = _score([claim_id])
    if not scores:
        raise HTTPException(503, "Fraud model not trained yet: run python ml/train.py")
    return {"claim_id": claim_id, "fraud_score": scores[claim_id],
            "risk_band": query_one("SELECT risk_band FROM v_claim_summary WHERE claim_id = %s", (claim_id,))["risk_band"]}


def _score(claim_ids):
    if not claim_ids or fraud.load_bundle() is None:
        return {}
    marks = ", ".join(["%s"] * len(claim_ids))
    rows = query(f"SELECT * FROM v_claim_features WHERE claim_id IN ({marks})", claim_ids)
    scores = fraud.score_rows(rows)
    if scores:
        with connection() as conn:
            cur = conn.cursor()
            cur.executemany("UPDATE claim SET fraud_score = %s WHERE claim_id = %s",
                            [(s, cid) for cid, s in scores.items()])
    return scores


# ============================ premiums / admin ============================
@app.post("/api/payments/{payment_id}/pay", tags=["premiums"])
def pay_premium(payment_id: int, body: PremiumPayIn = Body(default=PremiumPayIn())):
    callproc("sp_pay_premium", (payment_id, body.method))
    row = query_one("SELECT pp.*, p.status AS policy_status FROM premium_payment pp "
                    "JOIN policy p ON p.policy_id = pp.policy_id WHERE pp.payment_id = %s", (payment_id,))
    return row


@app.get("/api/overdue", tags=["premiums"])
def list_overdue(request: Request):
    return crud.list_view("overdue", dict(request.query_params))


@app.post("/api/admin/lapse-overdue", tags=["admin"])
def lapse_overdue(body: GraceIn = Body(default=GraceIn())):
    res = callproc("sp_lapse_overdue_policies", (body.grace_days, 0))
    return {"policies_lapsed": res[1], "grace_days": body.grace_days}


@app.post("/api/admin/expire-policies", tags=["admin"])
def expire_policies():
    res = callproc("sp_expire_policies", (0,))
    return {"policies_expired": res[0]}


@app.post("/api/admin/generate-instalments", tags=["admin"])
def generate_instalments():
    res = callproc("sp_generate_instalments", (date.today(), 0))
    return {"instalments_created": res[1]}


# ============================ reports ============================
@app.get("/api/reports/dashboard", tags=["reports"])
def dashboard():
    return {
        "kpis": query_one(DASHBOARD_SQL),
        "monthly": query("SELECT * FROM (SELECT * FROM v_monthly_claims ORDER BY month_start DESC LIMIT 12) x "
                         "ORDER BY month_start"),
        "claims_by_status": query("SELECT status, COUNT(*) AS n FROM claim GROUP BY status ORDER BY n DESC"),
        "loss_ratio": query("SELECT type_name, loss_ratio_pct FROM v_loss_ratio_by_type ORDER BY type_name"),
        "policies_by_type": query("SELECT pt.type_name, COUNT(*) AS n FROM policy p "
                                  "JOIN policy_type pt ON pt.type_id = p.type_id WHERE p.status = 'ACTIVE' "
                                  "GROUP BY pt.type_name ORDER BY n DESC"),
    }


@app.get("/api/reports", tags=["reports"])
def report_index():
    return [{"name": k, "title": v["title"]} for k, v in REPORTS.items()]


@app.get("/api/reports/{name}", tags=["reports"])
def report(name: str, format: str = "json"):
    rep = REPORTS.get(name)
    if not rep:
        raise HTTPException(404, f"Unknown report '{name}'")
    rows = query(rep["sql"])
    if format == "csv":
        buf = io.StringIO()
        if rows:
            w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
    return {"name": name, "title": rep["title"], "rows": rows}


# ============================ ML ============================
@app.post("/api/fraud/score-open", tags=["ml"])
def score_open():
    """Score every open claim and write claim.fraud_score."""
    ids = [r["claim_id"] for r in query("SELECT claim_id FROM claim WHERE status IN ('SUBMITTED', 'UNDER_REVIEW')")]
    if fraud.load_bundle() is None:
        raise HTTPException(503, "Fraud model not trained yet: run python ml/train.py")
    scores = _score(ids)
    # bands come from the view, i.e. from the active model's threshold in fraud_model
    bands = {r["risk_band"]: r["n"] for r in query(
        "SELECT risk_band, COUNT(*) AS n FROM v_claim_summary "
        "WHERE status IN ('SUBMITTED', 'UNDER_REVIEW') AND risk_band IS NOT NULL GROUP BY risk_band")}
    return {"scored": len(scores), "bands": {b: bands.get(b, 0) for b in ("HIGH", "MEDIUM", "LOW")}}


@app.get("/api/fraud/model", tags=["ml"])
def model_info():
    metrics = fraud.load_metrics()
    if metrics is None:
        raise HTTPException(503, "Fraud model not trained yet: run python ml/train.py")
    metrics["registry"] = query("SELECT * FROM fraud_model ORDER BY model_id DESC LIMIT 5")
    return metrics


# ============================ generic CRUD (F1) ============================
@app.get("/api/{resource}", tags=["crud"])
def crud_list(resource: str, request: Request):
    return crud.list_rows(resource, dict(request.query_params))


@app.get("/api/{resource}/{row_id}", tags=["crud"])
def crud_get(resource: str, row_id: str):
    return crud.get_row(resource, row_id)


@app.post("/api/{resource}", tags=["crud"], status_code=201)
def crud_create(resource: str, body: dict = Body(...)):
    row = crud.create_row(resource, body)
    if resource == "documents":
        # documents_attached is a model feature: re-score an open claim when its paperwork arrives
        open_claim = query_one("SELECT claim_id FROM claim WHERE claim_id = %s "
                               "AND status IN ('SUBMITTED', 'UNDER_REVIEW')", (row["claim_id"],))
        if open_claim:
            _score([open_claim["claim_id"]])
    return row


@app.put("/api/{resource}/{row_id}", tags=["crud"])
def crud_update(resource: str, row_id: str, body: dict = Body(...)):
    return crud.update_row(resource, row_id, body)


@app.delete("/api/{resource}/{row_id}", tags=["crud"])
def crud_delete(resource: str, row_id: str):
    return crud.delete_row(resource, row_id)


# ============================ static front end ============================
(ROOT / "docs" / "outputs" / "ml").mkdir(parents=True, exist_ok=True)
app.mount("/ml-assets", StaticFiles(directory=ROOT / "docs" / "outputs" / "ml"), name="ml-assets")
app.mount("/app", StaticFiles(directory=ROOT / "web", html=True), name="web")


@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse("/app/")
