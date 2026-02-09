"""
ml/train_model.py
=================
Train, calibrate, and evaluate the CVD and Diabetes risk models.

Run:
    python ml/train_model.py

Outputs:
    ml/model_bundle.pkl   — serialised bundle for the predictor
    ml/training_report.txt — human-readable evaluation report

Model choice: Logistic Regression (L2) + Platt calibration
Rationale: see AUDIT_AND_DESIGN.md Phase 3 Step 2
"""

from __future__ import annotations

import json
import warnings
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    roc_auc_score, brier_score_loss, precision_recall_curve,
    average_precision_score, confusion_matrix, classification_report
)
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.preprocessing import StandardScaler

from ml.data_pipeline import (
    FEATURE_COLS, TARGET_CVD, TARGET_DIABETES, load_or_generate
)

warnings.filterwarnings("ignore", category=UserWarning)

MODEL_OUT = Path(__file__).parent / "model_bundle.pkl"
REPORT_OUT = Path(__file__).parent / "training_report.txt"


# ─── Evaluation helpers ───────────────────────────────────────
def evaluate_model(
    clf,
    X_test: np.ndarray,
    y_test: np.ndarray,
    name: str,
    feature_names: list
) -> Dict[str, Any]:
    """Return a full evaluation dict + print results."""
    y_prob = clf.predict_proba(X_test)[:, 1]
    y_pred = (y_prob >= 0.5).astype(int)

    auc     = roc_auc_score(y_test, y_prob)
    brier   = brier_score_loss(y_test, y_prob)
    ap      = average_precision_score(y_test, y_prob)
    cm      = confusion_matrix(y_test, y_pred)

    # Sensitivity at 80% specificity
    from sklearn.metrics import roc_curve
    fpr, tpr, thresholds = roc_curve(y_test, y_prob)
    idx_80spec = np.argmin(np.abs(fpr - 0.20))   # specificity = 1 - fpr = 0.80
    sens_at_80spec = tpr[idx_80spec]

    # Expected Calibration Error (10 bins)
    prob_true, prob_pred = calibration_curve(y_test, y_prob, n_bins=10, strategy='quantile')
    ece = float(np.mean(np.abs(prob_true - prob_pred)))

    # Subgroup AUC by sex (if available — index 1 is sex_male in FEATURE_COLS)
    sex_col = 1  # FEATURE_COLS index for sex_male
    mask_m = X_test[:, sex_col] == 1
    mask_f = X_test[:, sex_col] == 0
    auc_male   = roc_auc_score(y_test[mask_m], y_prob[mask_m]) if mask_m.sum() > 10 and y_test[mask_m].nunique() > 1 else None
    auc_female = roc_auc_score(y_test[mask_f], y_prob[mask_f]) if mask_f.sum() > 10 and y_test[mask_f].nunique() > 1 else None

    # Age band subgroup
    age_col = 0
    results = {
        "name":               name,
        "n_test":             int(len(y_test)),
        "prevalence_test":    float(y_test.mean()),
        "roc_auc":            round(float(auc),    4),
        "brier_score":        round(float(brier),  4),
        "avg_precision":      round(float(ap),     4),
        "sensitivity_80spec": round(float(sens_at_80spec), 4),
        "ece":                round(float(ece),    4),
        "auc_male":           round(float(auc_male),   4) if auc_male   else None,
        "auc_female":         round(float(auc_female), 4) if auc_female else None,
        "confusion_matrix":   cm.tolist(),
    }

    lines = [
        f"\n{'='*60}",
        f"  MODEL: {name}",
        f"{'='*60}",
        f"  Test samples:          {len(y_test):,}",
        f"  Outcome prevalence:    {y_test.mean()*100:.1f}%",
        f"  ROC-AUC:               {auc:.4f}  (target: >0.70)",
        f"  Brier score:           {brier:.4f}  (target: <0.25)",
        f"  Avg precision:         {ap:.4f}",
        f"  Sensitivity@80%spec:   {sens_at_80spec:.4f}  (target: >0.60)",
        f"  ECE:                   {ece:.4f}  (target: <0.05)",
        f"  AUC males:             {auc_male:.4f}" if auc_male   else "  AUC males:             n/a",
        f"  AUC females:           {auc_female:.4f}" if auc_female else "  AUC females:           n/a",
        f"\n  Confusion matrix (threshold 0.5):",
        f"    TN={cm[0,0]:4d}  FP={cm[0,1]:4d}",
        f"    FN={cm[1,0]:4d}  TP={cm[1,1]:4d}",
        f"\n  Quality gates:",
        f"    AUC  {'✓ PASS' if auc  > 0.70 else '✗ FAIL (below 0.70)'}",
        f"    Brier {'✓ PASS' if brier < 0.25 else '✗ FAIL (above 0.25)'}",
        f"    ECE  {'✓ PASS' if ece  < 0.05 else '⚠ REVIEW (above 0.05)'}",
    ]
    if auc_male and auc_female:
        gap = abs(auc_male - auc_female)
        lines.append(f"    Fairness gap: {gap:.4f} {'✓' if gap < 0.08 else '⚠ REVIEW'}")
    print("\n".join(lines))

    return results


# ─── Training ─────────────────────────────────────────────────
def train(data_dir: str = "data") -> Dict[str, Any]:
    """Full train / evaluate / serialise pipeline."""
    print(f"[train_model] Starting training — {datetime.now().isoformat()}")

    df = load_or_generate(data_dir)

    X = df[FEATURE_COLS].values.astype(np.float64)
    y_cvd  = df[TARGET_CVD].values.astype(int)
    y_diab = df[TARGET_DIABETES].values.astype(int)

    # ── Fit scaler on full dataset (will be used at inference time) ──
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # ── Train/test split: last 20% chronologically / by index ────────
    # (In production: split by enrolment date, not random)
    split = int(len(X) * 0.80)
    X_train, X_test = X_scaled[:split], X_scaled[split:]
    y_cvd_train,  y_cvd_test  = y_cvd[:split],  y_cvd[split:]
    y_diab_train, y_diab_test = y_diab[:split], y_diab[split:]

    # ── Cross-validation (on training fold only, not test) ───────────
    skf    = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    base_lr = LogisticRegression(C=1.0, max_iter=1000, random_state=42, solver="lbfgs")

    cv_auc_cvd  = cross_val_score(base_lr, X_train, y_cvd_train,  cv=skf, scoring="roc_auc")
    cv_auc_diab = cross_val_score(base_lr, X_train, y_diab_train, cv=skf, scoring="roc_auc")

    print(f"\n[CV] CVD   5-fold AUC: {cv_auc_cvd.mean():.4f} ± {cv_auc_cvd.std():.4f}")
    print(f"[CV] Diab  5-fold AUC: {cv_auc_diab.mean():.4f} ± {cv_auc_diab.std():.4f}")

    # ── Train with Platt calibration (sigmoid method) ─────────────────
    # Calibration is trained on held-out folds via cross_val_predict,
    # so it doesn't overfit to training labels.
    cvd_clf = CalibratedClassifierCV(
        LogisticRegression(C=1.0, max_iter=1000, random_state=42, solver="lbfgs"),
        method="sigmoid", cv=5
    )
    cvd_clf.fit(X_train, y_cvd_train)

    diab_clf = CalibratedClassifierCV(
        LogisticRegression(C=1.0, max_iter=1000, random_state=42, solver="lbfgs"),
        method="sigmoid", cv=5
    )
    diab_clf.fit(X_train, y_diab_train)

    # ── Evaluate on hold-out test set ────────────────────────────────
    y_cvd_test_series  = pd.Series(y_cvd_test)
    y_diab_test_series = pd.Series(y_diab_test)

    cvd_metrics  = evaluate_model(cvd_clf,  X_test, y_cvd_test_series,  "CVD (10-year)",      FEATURE_COLS)
    diab_metrics = evaluate_model(diab_clf, X_test, y_diab_test_series, "Diabetes (10-year)", FEATURE_COLS)

    # ── Extract base LR coefficients for SHAP (from calibrated clf) ──
    # CalibratedClassifierCV wraps k estimators; we use the first for SHAP
    base_estimators_cvd  = [e.estimator for e in cvd_clf.calibrated_classifiers_]
    base_estimators_diab = [e.estimator for e in diab_clf.calibrated_classifiers_]

    # ── Compute feature importances (mean |coef| across CV folds) ────
    coef_cvd  = np.mean([e.coef_[0] for e in base_estimators_cvd],  axis=0)
    coef_diab = np.mean([e.coef_[0] for e in base_estimators_diab], axis=0)

    # Rank by absolute coefficient
    fi_cvd  = sorted(zip(FEATURE_COLS, coef_cvd),  key=lambda x: abs(x[1]), reverse=True)
    fi_diab = sorted(zip(FEATURE_COLS, coef_diab), key=lambda x: abs(x[1]), reverse=True)

    print("\n[Feature importance — CVD top 10 by |coef|]")
    for feat, coef in fi_cvd[:10]:
        direction = "↑ risk" if coef > 0 else "↓ risk"
        print(f"  {feat:25s}  {coef:+.4f}  {direction}")

    print("\n[Feature importance — Diabetes top 10 by |coef|]")
    for feat, coef in fi_diab[:10]:
        direction = "↑ risk" if coef > 0 else "↓ risk"
        print(f"  {feat:25s}  {coef:+.4f}  {direction}")

    # ── Build model bundle ────────────────────────────────────────────
    bundle = {
        "version":        "v1.0-synthetic",
        "training_date":  datetime.now().isoformat(),
        "data_source":    "synthetic (DEMO ONLY — not validated on real outcomes)",
        "feature_cols":   FEATURE_COLS,
        "scaler":         scaler,
        "models": {
            "CVD": {
                "clf":      cvd_clf,
                "metrics":  cvd_metrics,
                "coef":     coef_cvd.tolist(),
                "cv_auc_mean": float(cv_auc_cvd.mean()),
                "cv_auc_std":  float(cv_auc_cvd.std()),
            },
            "Diabetes": {
                "clf":      diab_clf,
                "metrics":  diab_metrics,
                "coef":     coef_diab.tolist(),
                "cv_auc_mean": float(cv_auc_diab.mean()),
                "cv_auc_std":  float(cv_auc_diab.std()),
            },
        },
        # Training-set statistics needed for SHAP background
        "feature_means": scaler.mean_.tolist(),
        "feature_stds":  scaler.scale_.tolist(),
    }

    # ── Save ──────────────────────────────────────────────────────────
    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, MODEL_OUT)
    print(f"\n[train_model] Bundle saved → {MODEL_OUT}")

    # ── Write text report ─────────────────────────────────────────────
    report_lines = [
        "HEALTH AI TRACKER — MODEL TRAINING REPORT",
        f"Generated: {datetime.now().isoformat()}",
        f"Data source: {bundle['data_source']}",
        "",
        "DISCLAIMER: These models are trained on synthetic data and are",
        "NOT validated against real patient outcomes. Output probabilities",
        "must not be used for clinical decision-making.",
        "",
        json.dumps({"CVD_metrics": cvd_metrics, "Diabetes_metrics": diab_metrics}, indent=2),
        "",
        "FEATURE COEFFICIENTS (CVD):",
        *[f"  {f:30s} {c:+.6f}" for f, c in fi_cvd],
        "",
        "FEATURE COEFFICIENTS (Diabetes):",
        *[f"  {f:30s} {c:+.6f}" for f, c in fi_diab],
    ]
    REPORT_OUT.write_text("\n".join(report_lines))
    print(f"[train_model] Report saved → {REPORT_OUT}")

    return bundle


if __name__ == "__main__":
    train()
