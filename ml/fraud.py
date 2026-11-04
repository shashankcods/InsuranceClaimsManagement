"""Shared fraud-model definitions: feature lists, model loading and scoring.

Features come from the v_claim_features view, which only exposes information
known at filing time (no status / assessment / payout / label -> no leakage).
"""
import json
from pathlib import Path

import joblib
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "ml" / "model.joblib"
METRICS_PATH = ROOT / "docs" / "outputs" / "ml" / "metrics.json"

NUMERIC = ["claimed_amount", "claim_ratio", "days_since_start", "days_to_end", "filing_delay",
           "customer_age", "prior_claims", "late_payments", "documents_attached", "non_network_provider"]
CATEGORICAL = ["claim_type", "policy_type"]
FEATURES = NUMERIC + CATEGORICAL

_model_cache = {"mtime": None, "bundle": None}


def load_bundle():
    """Returns {'model', 'threshold', 'name'} or None if not trained yet. Reloads if the file changed."""
    if not MODEL_PATH.exists():
        return None
    mtime = MODEL_PATH.stat().st_mtime
    if _model_cache["mtime"] != mtime:
        _model_cache["bundle"] = joblib.load(MODEL_PATH)
        _model_cache["mtime"] = mtime
    return _model_cache["bundle"]


def to_frame(rows):
    df = pd.DataFrame(rows)
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    for c in CATEGORICAL:
        df[c] = df[c].astype(str)
    return df


def score_rows(rows):
    """rows: dicts from v_claim_features. Returns {claim_id: probability}."""
    bundle = load_bundle()
    if bundle is None or not rows:
        return {}
    df = to_frame(rows)
    probs = bundle["model"].predict_proba(df[FEATURES])[:, 1]
    return {int(cid): round(float(p), 4) for cid, p in zip(df["claim_id"], probs)}


def load_metrics():
    if METRICS_PATH.exists():
        return json.loads(METRICS_PATH.read_text())
    return None
