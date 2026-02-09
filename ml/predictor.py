"""
ml/predictor.py
===============
Load model bundle, compute predictions with SHAP explanations,
and return fully safe, explained output.

This is the single entry point for all ML-based predictions.
The calling code (app_v5.py or integrate.py) should never touch
sklearn or shap directly.

Output contract (always returns, never raises to caller):
  - A dict of { disease_name: SafeOutput.to_dict() }
  - Always includes "Cancer" (RR-based, no ML)
  - Always includes "_health_age" (rule-based)
  - Always includes "_meta" (model version, data source, limitations)
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ml.data_pipeline import (
    engineer_features, features_to_array, imputation_count, FEATURE_COLS
)
from ml.safety import (
    compute_confidence, format_safe_output,
    CVD_BANDS, DIABETES_BANDS, HUMAN_LABELS,
    SafeOutput
)

# Keep import of risk_calculators for cancer and health age
# (these are retained as rule-based — see Phase 1 analysis for why
#  a data-driven cancer model is not appropriate here)
from risk_calculators import (
    cancer_lifestyle_risk, estimate_health_age,
    findrisc_diabetes  # kept as cross-check / fallback
)

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).parent / "model_bundle.pkl"
_BUNDLE: Optional[Dict] = None   # module-level cache


def _load_bundle() -> Optional[Dict]:
    global _BUNDLE
    if _BUNDLE is not None:
        return _BUNDLE
    if not MODEL_PATH.exists():
        logger.warning("Model bundle not found at %s — run ml/train_model.py first", MODEL_PATH)
        return None
    import joblib
    _BUNDLE = joblib.load(MODEL_PATH)
    logger.info("Loaded model bundle version=%s", _BUNDLE.get("version", "unknown"))
    return _BUNDLE


# ─── SHAP computation ─────────────────────────────────────────
def _compute_shap(
    bundle: Dict,
    disease: str,
    feat_scaled: np.ndarray,
    feat_raw: Dict[str, Any],
) -> Optional[Dict]:
    """
    Compute SHAP values using the LinearExplainer.

    For logistic regression: SHAP = coef * (x - mean_train)
    This is exact (no approximation), fast, and interpretable.

    Returns None on any failure (SHAP is best-effort; safety > crash).
    """
    try:
        import shap

        model_info = bundle["models"][disease]
        clf = model_info["clf"]
        # Use coefficients averaged across calibration folds
        coef = np.array(model_info["coef"])           # shape (n_features,)
        intercept_val = np.array(bundle["feature_means"])  # training means (pre-scale = 0 post)

        # For a StandardScaler: scaled_x = (x - mean) / std
        # SHAP_i = coef_i * scaled_x_i  (exact for linear model in scaled space)
        shap_vals = coef * feat_scaled[0]             # shape (n_features,)

        named = {FEATURE_COLS[i]: float(shap_vals[i]) for i in range(len(FEATURE_COLS))}

        # Filter out imputation flags from display (they're internal)
        display = {k: v for k, v in named.items() if not k.startswith("imp_")}

        # Top 3 risk-raising (positive SHAP) and risk-lowering (negative SHAP)
        sorted_items = sorted(display.items(), key=lambda x: x[1], reverse=True)
        top_risk = [
            {
                "feature": k,
                "label":   HUMAN_LABELS.get(k, k),
                "shap":    round(v, 4),
                "value":   round(feat_raw.get(k, 0), 2),
            }
            for k, v in sorted_items if v > 0
        ][:3]

        top_prot = [
            {
                "feature": k,
                "label":   HUMAN_LABELS.get(k, k),
                "shap":    round(v, 4),
                "value":   round(feat_raw.get(k, 0), 2),
            }
            for k, v in reversed(sorted_items) if v < 0
        ][:3]

        # ── Counterfactuals ───────────────────────────────────────────
        # For the top risk factors, simulate "what if this improved?"
        counterfactuals = _counterfactuals(bundle, disease, feat_raw, top_risk)

        return {
            "shap_values":      named,
            "top_risk_factors": top_risk,
            "top_protective":   top_prot,
            "counterfactuals":  counterfactuals,
        }
    except Exception as e:
        logger.exception("SHAP computation failed for %s: %s", disease, e)
        return None


def _counterfactuals(
    bundle: Dict,
    disease: str,
    feat_raw: Dict[str, Any],
    top_risk_factors: List[Dict]
) -> List[Dict]:
    """
    For each top risk factor, compute the predicted probability
    if that factor were improved to a clinically meaningful target.
    """
    clf = bundle["models"][disease]["clf"]
    scaler = bundle["scaler"]

    IMPROVEMENT_MAP = {
        # (description, feature_key, new_value)
        "smoking_current": ("Quit smoking",         "smoking_current",   0.0),
        "sbp":             ("Reduce SBP to 120 mmHg","sbp",              120.0),
        "bmi":             ("Reach BMI 25",          "bmi",              25.0),
        "avg_steps_k":     ("Walk 10k steps/day",    "avg_steps_k",       10.0),
        "fasting_glucose": ("Normalise glucose",     "fasting_glucose",   90.0),
        "hba1c":           ("Normalise HbA1c",       "hba1c",              5.0),
        "ldl_chol":        ("Reduce LDL to 100",     "ldl_chol",         100.0),
        "total_chol":      ("Reduce total chol to 190","total_chol",     190.0),
        "chol_ratio":      ("Reduce chol ratio",     "chol_ratio",         3.5),
        "waist_cm":        ("Reduce waist 5cm",      "waist_cm",    feat_raw.get("waist_cm", 90) - 5),
    }

    counterfactuals = []
    # Current probability (recompute from raw to be safe)
    try:
        base_arr = features_to_array(feat_raw)
        base_scaled = scaler.transform(base_arr)
        base_prob = float(clf.predict_proba(base_scaled)[0, 1])
    except Exception:
        return []

    for factor_info in top_risk_factors[:3]:
        feat_key = factor_info["feature"]
        if feat_key not in IMPROVEMENT_MAP:
            continue
        desc, change_key, new_val = IMPROVEMENT_MAP[feat_key]

        # Only generate if improvement is meaningful
        if new_val >= feat_raw.get(change_key, new_val):
            continue   # value is already at or below target

        modified = dict(feat_raw)
        modified[change_key] = new_val

        # Recompute derived features
        if change_key in ("total_chol", "hdl_chol"):
            hdl = modified.get("hdl_chol", 50.0)
            tc  = modified.get("total_chol", 195.0)
            modified["chol_ratio"] = tc / hdl if hdl > 0 else 4.0
        if change_key == "sbp":
            modified["pulse_pressure"] = new_val - modified.get("dbp", 78.0)

        try:
            arr  = features_to_array(modified)
            scaled = scaler.transform(arr)
            new_prob = float(clf.predict_proba(scaled)[0, 1])
            delta = new_prob - base_prob  # negative = improvement
            if delta < -0.005:            # only show meaningful deltas
                counterfactuals.append({
                    "change":       desc,
                    "new_risk_pct": round(new_prob * 100, 1),
                    "delta_pct":    round(delta  * 100, 1),
                })
        except Exception:
            continue

    return counterfactuals


# ─── Main prediction entry point ─────────────────────────────
def predict(
    user: Dict[str, Any],
    labs: Dict[str, Any],
    daily_rows: List[Dict],
    daily_count: int
) -> Dict[str, Any]:
    """
    Full prediction pipeline. Always returns — never raises.

    Returns:
      {
        "CVD":       SafeOutput.to_dict() or gated dict,
        "Diabetes":  SafeOutput.to_dict() or gated dict,
        "Cancer":    dict (rule-based),
        "_health_age": dict,
        "_meta":     {...},
      }
    """
    results: Dict[str, Any] = {}
    bundle = _load_bundle()

    # ── Gate 1: profile completeness ─────────────────────────
    if not all(user.get(f) for f in ["age", "sex", "height", "weight"]):
        gated = _gated_response("profile",
            "Complete your profile (age, sex, height, weight) to unlock predictions.")
        return {d: gated for d in ["CVD", "Diabetes", "Cancer"]}

    # ── Gate 2: minimum 7 daily entries ──────────────────────
    if daily_count < 7:
        days_left = 7 - daily_count
        gated = _gated_response("daily_log",
            f"Log {days_left} more day{'s' if days_left != 1 else ''} to unlock predictions. "
            f"({daily_count}/7 days so far)")
        return {d: gated for d in ["CVD", "Diabetes", "Cancer"]}

    # ── Gate 3: any lab entry ─────────────────────────────────
    has_lab = any(
        labs.get(k) not in (None, "", 0)
        for k in ["total_cholesterol", "hdl_cholesterol",
                  "fasting_glucose", "hba1c", "hs_crp"]
    )
    if not has_lab:
        gated = _gated_response("labs",
            "Enter at least one blood test result to unlock predictions.")
        return {d: gated for d in ["CVD", "Diabetes", "Cancer"]}

    # ── Feature engineering ───────────────────────────────────
    try:
        feat = engineer_features(user, labs)
    except ValueError as e:
        gated = _gated_response("profile", str(e))
        return {d: gated for d in ["CVD", "Diabetes", "Cancer"]}

    # Compute derived lifestyle means
    def mean_col(col, default=0.0):
        vals = [r.get(col) for r in daily_rows if r.get(col) is not None]
        return float(np.mean(vals)) if vals else default

    avg_steps  = mean_col("steps", 5000.0)
    avg_sleep  = mean_col("sleep", 7.0)

    feat["avg_steps_k"] = avg_steps / 1000.0
    feat["avg_sleep"]   = avg_sleep

    feat_arr    = features_to_array(feat)
    confidence  = compute_confidence(feat, user, daily_count)

    sbp             = float(feat.get("sbp", 120))
    current_smoker  = feat.get("smoking_current", 0) == 1

    version     = bundle["version"] if bundle else "no-model"
    data_source = bundle.get("data_source", "unknown") if bundle else "n/a"
    source_cvd  = "Logistic Regression (synthetic data, DEMO) + ACC/AHA PCE reference"
    source_diab = "Logistic Regression (synthetic data, DEMO) + FINDRISC reference"

    # ── CVD prediction ────────────────────────────────────────
    if bundle:
        try:
            scaler   = bundle["scaler"]
            feat_scaled = scaler.transform(feat_arr)
            cvd_clf  = bundle["models"]["CVD"]["clf"]

            # Age gate for PCE compatibility
            if feat.get("age", 45) < 30:
                cvd_out = _gated_response("age_range",
                    "CVD model not validated for ages below 30.")
            else:
                cvd_prob = float(cvd_clf.predict_proba(feat_scaled)[0, 1])
                shap_cvd = _compute_shap(bundle, "CVD", feat_scaled, feat)
                cvd_out  = format_safe_output(
                    "CVD", cvd_prob, shap_cvd, confidence,
                    CVD_BANDS, source_cvd, version, data_source,
                    sbp=sbp, current_smoker=current_smoker
                ).to_dict()
                cvd_out["risk_pct"] = round(cvd_prob * 100, 1)
        except Exception as e:
            logger.exception("CVD prediction failed: %s", e)
            cvd_out = _gated_response("model_error", f"Prediction failed: {e}")
    else:
        cvd_out = _gated_response("no_model",
            "ML model not trained. Run: python -m ml.train_model")
    results["CVD"] = cvd_out

    # ── Diabetes prediction ───────────────────────────────────
    if bundle:
        try:
            diab_clf = bundle["models"]["Diabetes"]["clf"]
            diab_prob = float(diab_clf.predict_proba(feat_scaled)[0, 1])
            shap_diab = _compute_shap(bundle, "Diabetes", feat_scaled, feat)
            diab_out  = format_safe_output(
                "Diabetes", diab_prob, shap_diab, confidence,
                DIABETES_BANDS, source_diab, version, data_source,
                sbp=sbp, current_smoker=current_smoker
            ).to_dict()
            diab_out["risk_pct"] = round(diab_prob * 100, 1)

            # Annotate with FINDRISC cross-check
            try:
                waist = float(user.get("waist_cm") or (94 if feat.get("sex_male") else 80))
                fi = findrisc_diabetes(
                    feat["age"], feat["bmi"], waist,
                    "male" if feat.get("sex_male") else "female",
                    feat["avg_steps_k"] * 1000 >= 7500,
                    mean_col("veg_servings", 0) >= 2,
                    bool(feat.get("bp_medication")),
                    bool(user.get("high_glucose_history")),
                    int(user.get("family_history_diabetes") or 0)
                )
                diab_out["findrisc_score"]    = fi.get("score")
                diab_out["findrisc_category"] = fi.get("risk_category")
            except Exception:
                pass
        except Exception as e:
            logger.exception("Diabetes prediction failed: %s", e)
            diab_out = _gated_response("model_error", f"Prediction failed: {e}")
    else:
        diab_out = _gated_response("no_model",
            "ML model not trained. Run: python -m ml.train_model")
    results["Diabetes"] = diab_out

    # ── Cancer (rule-based — see Phase 1 rationale) ───────────
    sex     = str(user.get("sex", "male")).lower()
    smoker  = str(user.get("smoking_status", "never")) == "current"
    ex_smkr = str(user.get("smoking_status", "never")) == "ex"
    canc = cancer_lifestyle_risk(
        feat["age"], feat["bmi"], sex, smoker, ex_smkr,
        float(user.get("alcohol_per_week") or 0),
        feat["avg_steps_k"] * 1000 >= 7500,
        mean_col("red_meat_servings", 2.0),
        mean_col("processed_meat", 0.0) > 0,
        mean_col("veg_servings", 0.0) >= 2,
        bool(user.get("family_history_cancer"))
    )
    canc["confidence_score"] = confidence["score"]
    canc["confidence_label"] = confidence["label"]
    canc["data_source"] = "WCRF/AICR 2018 + IARC Monographs (rule-based, not ML)"
    results["Cancer"] = canc

    # ── Health Age (rule-based) ────────────────────────────────
    ha = estimate_health_age(
        feat["age"], feat["bmi"], sbp, current_smoker,
        avg_sleep, avg_steps,
        mean_col("stress_level", 5.0),
        feat.get("total_chol") if not feat.get("imp_total_chol") else None,
        feat.get("fasting_glucose") if not feat.get("imp_fasting_glucose") else None,
        feat.get("hba1c") if not feat.get("imp_hba1c") else None,
    )
    results["_health_age"] = ha

    # ── Meta ──────────────────────────────────────────────────
    results["_meta"] = {
        "model_version":   version,
        "data_source":     data_source,
        "confidence_score": confidence["score"],
        "confidence_label": confidence["label"],
        "imputed_features": imputation_count(feat),
        "daily_count":      daily_count,
        "global_warnings":  confidence["warnings"],
        "global_limitations": confidence["limitations"],
        "critical_disclaimer": (
            "These predictions are generated by a model trained on synthetic data. "
            "They are for educational demonstration only and must not be used for "
            "clinical decision-making. No regulatory approval has been obtained."
        )
    }

    return results


def _gated_response(gate: str, note: str) -> Dict[str, Any]:
    return {
        "risk_pct": None, "relative_risk": None,
        "risk_band_label": "—",
        "risk_band_cat": note,
        "risk_category": note,
        "color": "gray", "gate": gate, "note": note,
        "top_risk_factors": [], "top_protective": [],
        "counterfactuals": [], "modifiable_factors": [],
        "source": "", "model_version": "n/a",
        "confidence_score": 0, "confidence_label": "N/A",
        "warnings": [], "limitations": [],
        "referral": False,
    }
