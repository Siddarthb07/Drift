"""
ml/integrate.py
===============
Drop-in integration layer between ml/predictor.py and app_v5.py.

HOW TO SWITCH app_v5.py to use the ML layer:
---------------------------------------------
In app_v5.py, change ONE line:

    # Before (rule-based):
    from risk_calculators import (...)
    ...
    risk = compute_risk_scores(user, daily, labs)

    # After (ML + SHAP + safety layer):
    from ml.integrate import compute_risk_scores_ml as compute_risk_scores
    ...
    risk = compute_risk_scores(user, daily, labs)

That is the complete change. Everything else (templates, routes,
gating logic) is compatible with both return formats.

FIRST-RUN SETUP:
    python -m ml.train_model   # trains and saves ml/model_bundle.pkl

PREREQUISITES:
    pip install scikit-learn shap joblib
"""

from __future__ import annotations

from typing import Any, Dict, List

from ml.predictor import predict


def compute_risk_scores_ml(
    user: Dict[str, Any],
    daily_rows: List[Dict],
    labs: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Wraps ml.predictor.predict() and normalises its output
    to the same keys used by app_v5.py's Jinja2 templates.

    Template-compatible keys guaranteed:
      - risk_pct          (float or None)
      - relative_risk     (float or None, Cancer only)
      - risk_category     (str)
      - color             (str: green/yellow/orange/red/gray)
      - gate              (str or None)
      - note              (str or None)
      - source            (str)
      - modifiable_factors (list — mapped from SHAP top factors)
      - confidence_score  (int)
      - confidence_label  (str)
      - warnings          (list of str)
      - referral          (bool)

    Additional ML-only keys (used by enhanced dashboard template):
      - risk_band_label   (str: "10–20%")
      - top_risk_factors  (list of SHAP dicts)
      - top_protective    (list of SHAP dicts)
      - counterfactuals   (list of dicts)
      - findrisc_score    (int, Diabetes only)
      - _meta             (global metadata dict)
    """
    daily_count = len(daily_rows)
    raw = predict(user, labs, daily_rows, daily_count)

    out: Dict[str, Any] = {}

    for disease in ["CVD", "Diabetes", "Cancer"]:
        d = raw.get(disease, {})

        # Map SHAP top factors to the "modifiable_factors" format
        # that existing templates understand
        modifiable = []
        for f in d.get("top_risk_factors", []):
            modifiable.append({
                "factor": f.get("label", f.get("feature", "")),
                "impact": f"SHAP: {f['shap']:+.3f}",
                "action": _action_for(f.get("feature", ""))
            })
        # Also include counterfactual-based actions
        for cf in d.get("counterfactuals", []):
            modifiable.append({
                "factor": cf.get("change", ""),
                "impact": f"{cf.get('delta_pct', 0):+.1f}% risk change",
                "action": f"New estimated risk: {cf.get('new_risk_pct', '?')}%"
            })

        out[disease] = {
            # Core display keys (template-compatible)
            "risk_pct":          d.get("risk_pct"),
            "relative_risk":     d.get("relative_risk"),       # Cancer RR
            "risk_category":     d.get("risk_band_cat") or d.get("risk_category", "—"),
            "color":             d.get("color", "gray"),
            "gate":              d.get("gate"),
            "note":              d.get("note"),
            "source":            d.get("source", ""),
            "modifiable_factors": modifiable[:5],
            # Safety metadata
            "confidence_score":  d.get("confidence_score", 0),
            "confidence_label":  d.get("confidence_label", "N/A"),
            "confidence_color":  d.get("confidence_color", "gray"),
            "warnings":          d.get("warnings", []),
            "limitations":       d.get("limitations", []),
            "referral":          d.get("referral", False),
            # ML-specific (bonus display)
            "risk_band_label":   d.get("risk_band_label", "—"),
            "top_risk_factors":  d.get("top_risk_factors", []),
            "top_protective":    d.get("top_protective", []),
            "counterfactuals":   d.get("counterfactuals", []),
            "score":             d.get("findrisc_score"),         # FINDRISC
            "findrisc_category": d.get("findrisc_category"),
            "lifestyle_score":   d.get("lifestyle_score"),        # Cancer
        }

    # Pass through unchanged
    out["_health_age"] = raw.get("_health_age", {})
    out["_meta"]       = raw.get("_meta", {})
    out["_daily_count"] = daily_count

    return out


_ACTION_MAP = {
    "smoking_current":  "Quitting smoking is the single most impactful intervention for CVD and cancer risk.",
    "sbp":              "Blood pressure reduction through medication, DASH diet, and reduced sodium.",
    "bmi":              "Even 5–7% weight loss significantly reduces cardiovascular and diabetes risk.",
    "avg_steps_k":      "Target 10,000 steps/day; even 7,500 meaningfully reduces risk.",
    "fasting_glucose":  "Reduce refined carbohydrates; increase fibre; consult doctor for HbA1c management.",
    "hba1c":            "Glycaemic control through diet, exercise, and medication review.",
    "ldl_chol":         "Statin therapy and dietary saturated fat reduction.",
    "total_chol":       "Reduce dietary saturated and trans fats; increase omega-3s.",
    "chol_ratio":       "Improve HDL via exercise and reduce LDL via diet or medication.",
    "waist_cm":         "Abdominal fat reduction through aerobic exercise and calorie deficit.",
    "avg_sleep":        "Target 7–9 hours consistent sleep; address sleep apnoea if present.",
    "family_cvd":       "Non-modifiable — discuss enhanced screening with your doctor.",
    "family_diabetes":  "Non-modifiable — lifestyle measures especially important given family history.",
}

def _action_for(feature: str) -> str:
    return _ACTION_MAP.get(feature, "Consult your healthcare provider for personalised advice.")
