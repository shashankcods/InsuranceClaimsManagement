"""Train and evaluate the claim fraud classifier (design doc section 10).

    python ml/train.py

1. Load features from v_claim_features + label claim.fraud_flag, resolved claims only.
2. Stratified 80/20 split (seed 42); the 20% test split is touched exactly once.
3. Compare logistic regression, random forest and histogram gradient boosting by
   5-fold CV ROC-AUC on the training split (class weights for the ~9% positives).
4. Choose the decision threshold from OUT-OF-FOLD training predictions (max F1).
5. Report test metrics, confusion matrix, permutation importance, charts.
6. Refit the chosen model on all resolved claims, save ml/model.joblib and register
   it (with its threshold) as the active row of the fraud_model table.

Honesty: the data is synthetic with a built-in signal, so these metrics show the
pipeline works end to end, not real-world fraud-detection accuracy.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import joblib
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mysql.connector
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, confusion_matrix, f1_score, precision_recall_curve,
                             precision_score, recall_score, roc_auc_score, roc_curve)
from sklearn.model_selection import StratifiedKFold, cross_val_predict, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api.db import ENV  # noqa: E402
from ml.fraud import CATEGORICAL, FEATURES, METRICS_PATH, MODEL_PATH, NUMERIC, to_frame  # noqa: E402

SEED = 42
OUT = METRICS_PATH.parent
OUT.mkdir(parents=True, exist_ok=True)


def connect():
    return mysql.connector.connect(host=ENV["DB_HOST"], port=int(ENV["DB_PORT"]), user=ENV["DB_USER"],
                                   password=ENV["DB_PASSWORD"], database=ENV["DB_NAME"], autocommit=True)


def register_model(name, threshold, auc, n):
    """Make this model the active row in fraud_model; its threshold drives the risk bands."""
    conn = connect()
    model_id = conn.cursor().callproc("sp_register_model", (name, round(threshold, 4), round(auc, 4), n, 0))[4]
    conn.close()
    return model_id


def load_data():
    conn = connect()
    cur = conn.cursor(dictionary=True)
    cur.execute("""SELECT f.*, c.fraud_flag
                     FROM v_claim_features f JOIN claim c ON c.claim_id = f.claim_id
                    WHERE c.status IN ('APPROVED', 'REJECTED', 'PAID')""")
    rows = cur.fetchall()
    conn.close()
    df = to_frame(rows)
    df["fraud_flag"] = df["fraud_flag"].astype(int)
    return df


def preprocessor(scale):
    num = StandardScaler() if scale else "passthrough"
    return ColumnTransformer([("num", num, NUMERIC),
                              ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL)])


def candidates():
    return {
        "Logistic regression": Pipeline([("prep", preprocessor(True)),
                                         ("clf", LogisticRegression(max_iter=2000, class_weight="balanced"))]),
        "Random forest": Pipeline([("prep", preprocessor(False)),
                                   ("clf", RandomForestClassifier(n_estimators=300, min_samples_leaf=5,
                                                                  class_weight="balanced_subsample",
                                                                  random_state=SEED, n_jobs=-1))]),
        "Hist. gradient boosting": Pipeline([("prep", preprocessor(False)),
                                             ("clf", HistGradientBoostingClassifier(
                                                 max_iter=200, learning_rate=0.05, max_leaf_nodes=15,
                                                 class_weight="balanced", random_state=SEED))]),
    }


def main():
    df = load_data()
    X, y = df[FEATURES], df["fraud_flag"].values
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.20, stratify=y, random_state=SEED)
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
    print(f"resolved claims={len(df)}  positives={y.sum()} ({100 * y.mean():.1f}%)  train={len(y_tr)} test={len(y_te)}")

    # ---- model selection on the training split only ----
    cv_results = {}
    for name, model in candidates().items():
        scores = cross_val_score(model, X_tr, y_tr, cv=cv, scoring="roc_auc")
        cv_results[name] = {"cv_roc_auc_mean": round(scores.mean(), 4), "cv_roc_auc_std": round(scores.std(), 4)}
        print(f"  {name:25s} CV ROC-AUC = {scores.mean():.4f} +/- {scores.std():.4f}")
    best_name = max(cv_results, key=lambda n: cv_results[n]["cv_roc_auc_mean"])
    print(f"selected: {best_name}")

    # ---- threshold from out-of-fold predictions (never from the test set) ----
    best = candidates()[best_name]
    oof = cross_val_predict(best, X_tr, y_tr, cv=cv, method="predict_proba")[:, 1]
    prec, rec, thr = precision_recall_curve(y_tr, oof)
    f1s = 2 * prec[:-1] * rec[:-1] / np.clip(prec[:-1] + rec[:-1], 1e-9, None)
    threshold = float(thr[int(np.argmax(f1s))])
    print(f"threshold (max OOF F1) = {threshold:.3f}")

    # ---- single evaluation on the untouched test split ----
    best.fit(X_tr, y_tr)
    p_te = best.predict_proba(X_te)[:, 1]
    pred = (p_te >= threshold).astype(int)
    cm = confusion_matrix(y_te, pred)
    test = {
        "roc_auc": round(roc_auc_score(y_te, p_te), 4),
        "pr_auc": round(average_precision_score(y_te, p_te), 4),
        "precision": round(precision_score(y_te, pred, zero_division=0), 4),
        "recall": round(recall_score(y_te, pred), 4),
        "f1": round(f1_score(y_te, pred), 4),
        "base_rate": round(float(y_te.mean()), 4),
        "confusion_matrix": {"tn": int(cm[0, 0]), "fp": int(cm[0, 1]), "fn": int(cm[1, 0]), "tp": int(cm[1, 1])},
    }
    print("test:", {k: v for k, v in test.items() if k != "confusion_matrix"}, test["confusion_matrix"])

    imp = permutation_importance(best, X_te, y_te, scoring="roc_auc", n_repeats=20, random_state=SEED)
    importance = sorted(({"feature": f, "importance": round(float(m), 4), "std": round(float(s), 4)}
                         for f, m, s in zip(FEATURES, imp.importances_mean, imp.importances_std)),
                        key=lambda d: -d["importance"])

    # ---- charts ----
    fpr, tpr, _ = roc_curve(y_te, p_te)
    fig, ax = plt.subplots(figsize=(5, 4.2))
    ax.plot(fpr, tpr, lw=2, label=f"{best_name} (AUC {test['roc_auc']:.3f})")
    ax.plot([0, 1], [0, 1], "--", color="grey", lw=1, label="chance")
    ax.set(xlabel="False positive rate", ylabel="True positive rate", title="ROC curve (test split)")
    ax.legend(loc="lower right", fontsize=8); fig.tight_layout(); fig.savefig(OUT / "roc_curve.png", dpi=130); plt.close(fig)

    p2, r2, _ = precision_recall_curve(y_te, p_te)
    fig, ax = plt.subplots(figsize=(5, 4.2))
    ax.plot(r2, p2, lw=2, label=f"PR-AUC {test['pr_auc']:.3f}")
    ax.axhline(test["base_rate"], ls="--", color="grey", lw=1, label=f"base rate {test['base_rate']:.3f}")
    ax.set(xlabel="Recall", ylabel="Precision", title="Precision-recall (test split)")
    ax.legend(fontsize=8); fig.tight_layout(); fig.savefig(OUT / "pr_curve.png", dpi=130); plt.close(fig)

    fig, ax = plt.subplots(figsize=(4.2, 3.8))
    ax.imshow(cm, cmap="Blues")
    for (i, j), v in np.ndenumerate(cm):
        ax.text(j, i, str(v), ha="center", va="center", fontsize=13,
                color="white" if v > cm.max() / 2 else "black")
    ax.set_xticks([0, 1], ["Genuine", "Fraud"]); ax.set_yticks([0, 1], ["Genuine", "Fraud"])
    ax.set(xlabel="Predicted", ylabel="Actual", title=f"Confusion matrix (t={threshold:.2f})")
    fig.tight_layout(); fig.savefig(OUT / "confusion_matrix.png", dpi=130); plt.close(fig)

    fig, ax = plt.subplots(figsize=(6, 4.2))
    top = importance[::-1]
    ax.barh([d["feature"] for d in top], [d["importance"] for d in top], xerr=[d["std"] for d in top], color="#4C72B0")
    ax.set(xlabel="Drop in ROC-AUC when shuffled", title="Permutation importance (test split)")
    fig.tight_layout(); fig.savefig(OUT / "feature_importance.png", dpi=130); plt.close(fig)

    # ---- final model on all resolved claims, saved with the OOF threshold ----
    final = candidates()[best_name].fit(X, y)
    joblib.dump({"model": final, "threshold": threshold, "name": best_name}, MODEL_PATH)

    metrics = {
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "selected_model": best_name, "threshold": round(threshold, 4),
        "n_resolved": int(len(df)), "n_positive": int(y.sum()), "n_train": int(len(y_tr)), "n_test": int(len(y_te)),
        "cv": cv_results, "test": test, "permutation_importance": importance,
        "features": FEATURES,
        "charts": ["roc_curve.png", "pr_curve.png", "confusion_matrix.png", "feature_importance.png"],
        "note": "Synthetic data with a built-in fraud signal: metrics demonstrate the pipeline, not real-world accuracy.",
    }
    metrics["model_id"] = register_model(best_name, threshold, test["roc_auc"], int(len(df)))
    METRICS_PATH.write_text(json.dumps(metrics, indent=2))
    print(f"saved {MODEL_PATH} and {METRICS_PATH}; registered as fraud_model #{metrics['model_id']}")


if __name__ == "__main__":
    main()
