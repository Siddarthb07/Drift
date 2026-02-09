"""
ml/safety.py
============
Safety layer: confidence scoring, edge-case detection, output formatting.

This module sits between the raw model output and the UI.
It is the difference between a research notebook and a system
that should not harm people.

Design principles:
  1. Never suppress information — lower confidence = more explicit uncertainty
  2. Referral threshold is conservative (errs toward caution)
  3. Every output includes its own explanation of limitations
  4. Risk is presented as a BAND, not a false-precision point estimate
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ─── Risk bands ───────────────────────────────────────────────
# Wider bands = honest representation of model uncertainty.
# Narrower bands would require clinical validation on outcome data.

CVD_BANDS = [
    (0.00, 0.05, "<5%",   "Low",          "green"),
    (0.05, 0.10, "5–10%", "Moderate",     "yellow"),
    (0.10, 0.20, "10–20%","Intermediate", "orange"),
    (0.20, 0.30, "20–30%","High",         "red"),
    (0.30, 1.00, ">30%",  "Very high",    "red"),
]

DIABETES_BANDS = [
    (0.00, 0.05, "<5%",    "Low",           "green"),
    (0.05, 0.17, "5–17%",  "Slightly elevated", "yellow"),
    (0.17, 0.33, "17–33%", "Moderate",      "orange"),
    (0.33, 0.50, "33–50%", "High",          "red"),
    (0.50, 1.00, ">50%",   "Very high",     "red"),
]

CANCER_BANDS = [
    (0.00, 0.90, "Below avg",      "Below population average",     "green"),
    (0.90, 1.30, "Near avg",       "Near population average",      "yellow"),
    (1.30, 1.80, "Moderately ↑",   "Moderately above average",     "orange"),
    (1.80, 99.0, "Substantially ↑","Substantially elevated",       "red"),
]


def _get_band(value: float, bands: list) -> Dict[str, str]:
    for lo, hi, label, category, color in bands:
        if lo <= value < hi:
            return {"label": label, "category": category, "color": color}
    return {"label": "Unknown", "category": "Unknown", "color": "gray"}


# ─── Confidence scoring ───────────────────────────────────────
def compute_confidence(
    feat: Dict[str, Any],
    user: Dict[str, Any],
    daily_count: int
) -> Dict[str, Any]:
    """
    Compute a confidence score (0–100) for this prediction.

    Deductions are applied for:
    - Missing / imputed features (each reduces reliability)
    - Age outside training distribution
    - Population known to be underserved by base algorithms
    - Insufficient daily log history
    - South Asian background (PCE not validated in this population)

    Returns a dict with score, label, and list of warnings.
    """
    score = 100
    warnings: List[str] = []
    limitations: List[str] = []

    # ── Missing labs ─────────────────────────────────────────
    imputed_count = sum(int(feat.get(k, 0)) for k in feat if k.startswith("imp_"))
    critical_missing = []
    if feat.get("imp_total_chol"):
        critical_missing.append("Total Cholesterol")
    if feat.get("imp_hdl_chol"):
        critical_missing.append("HDL Cholesterol")
    if feat.get("imp_fasting_glucose"):
        critical_missing.append("Fasting Glucose")

    if critical_missing:
        deduction = len(critical_missing) * 12
        score -= deduction
        warnings.append(f"Key labs missing (imputed): {', '.join(critical_missing)}")
        limitations.append(
            f"{', '.join(critical_missing)} not entered — median population values used. "
            f"Enter your actual lab results for a more accurate estimate."
        )

    if feat.get("imp_waist_cm"):
        score -= 8
        warnings.append("Waist circumference not entered (imputed to population median)")

    # ── Age range ─────────────────────────────────────────────
    age = feat.get("age", 50)
    if age < 30:
        score -= 20
        warnings.append("Age < 30: models have limited training data for this age group")
        limitations.append("CVD and diabetes models are most reliable for ages 30–79.")
    elif age > 79:
        score -= 15
        warnings.append("Age > 79: PCE and FINDRISC were not validated above 79")
        limitations.append("Risk calculator accuracy decreases above age 79.")

    # ── Population coverage ───────────────────────────────────
    race = str(user.get("race", "white")).lower()
    if race not in ("white", "aa"):
        score -= 15
        warnings.append("PCE validated only on White and African American cohorts")
        limitations.append(
            "The cardiovascular risk equation was validated on US White and African American "
            "cohorts. South Asian individuals have substantially higher CVD and T2D risk at "
            "lower BMI thresholds. Your score may underestimate your true risk — discuss "
            "with your doctor."
        )

    # ── Data history ──────────────────────────────────────────
    if daily_count < 14:
        deduction = max(0, (14 - daily_count) * 2)
        score -= deduction
        if daily_count < 10:
            warnings.append(f"Only {daily_count} days of lifestyle data — 14+ recommended")
            limitations.append(
                f"Lifestyle features (steps, sleep, stress) are averaged over {daily_count} days. "
                "At least 14 days of logging is recommended for stable averages."
            )

    # ── Extreme values ────────────────────────────────────────
    if feat.get("sbp", 120) > 180:
        score -= 10
        warnings.append("Very high systolic BP (>180 mmHg) — seek medical evaluation")
        limitations.append(
            "Systolic BP above 180 mmHg requires urgent medical evaluation. "
            "This prediction tool is not a substitute for clinical assessment."
        )
    if feat.get("bmi", 25) > 45:
        score -= 10
        warnings.append("BMI > 45: model may underestimate risk at extreme obesity")

    score = max(0, min(100, score))

    # ── Label ─────────────────────────────────────────────────
    if score >= 70:
        label, color = "MODERATE", "yellow"
        # Note: HIGH is intentionally reserved for clinically validated systems
    elif score >= 40:
        label, color = "LOW", "orange"
    else:
        label, color = "VERY LOW", "red"

    return {
        "score": score,
        "label": label,
        "color": color,
        "warnings": warnings,
        "limitations": limitations,
        "imputed_count": imputed_count,
    }


# ─── Referral trigger ─────────────────────────────────────────
def referral_recommended(
    risk_pct: Optional[float],
    confidence: Dict[str, Any],
    sbp: float = 120,
    current_smoker: bool = False
) -> bool:
    """
    Return True if a prominent "speak to a doctor" recommendation
    should be displayed — NOT suppressed to a footer disclaimer.
    """
    if risk_pct is None:
        return False
    # Absolute risk threshold
    if risk_pct >= 15.0:
        return True
    # High risk with low confidence (uncertainty alone is a referral signal)
    if risk_pct >= 10.0 and confidence["score"] < 50:
        return True
    # Clinical red flags independent of model output
    if sbp >= 160 or current_smoker:
        return True
    return False


# ─── Output formatter ─────────────────────────────────────────
@dataclass
class SafeOutput:
    """Structured, safe prediction output for one disease."""
    disease:          str
    # Point estimate (for internal use / logging only)
    raw_probability:  Optional[float]
    # Display output
    risk_band_label:  str          # e.g. "10–20%"
    risk_band_cat:    str          # e.g. "Intermediate"
    color:            str          # green/yellow/orange/red/gray
    # Explainability
    top_risk_factors: List[Dict]   # [{"feature": ..., "label": ..., "shap": ...}]
    top_protective:   List[Dict]
    counterfactuals:  List[Dict]   # [{"change": ..., "new_risk_pct": ..., "delta": ...}]
    # Safety metadata
    confidence_score: int
    confidence_label: str
    confidence_color: str
    warnings:         List[str]
    limitations:      List[str]
    referral:         bool
    gate:             Optional[str]  # None = all gates passed
    note:             Optional[str]
    source:           str
    model_version:    str
    data_source:      str
    disclaimer:       str = field(default=(
        "This is a statistical estimate for informational purposes only. "
        "It is NOT a clinical diagnosis and does NOT replace consultation "
        "with a qualified healthcare provider. Do not make medical decisions "
        "based on this output alone."
    ))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


HUMAN_LABELS = {
    # Lipids
    "total_chol":     "Total cholesterol",
    "hdl_chol":       "HDL ('good') cholesterol",
    "ldl_chol":       "LDL ('bad') cholesterol",
    "chol_ratio":     "Cholesterol ratio (total/HDL)",
    # Vitals
    "sbp":            "Systolic blood pressure",
    "dbp":            "Diastolic blood pressure",
    "pulse_pressure": "Pulse pressure (SBP–DBP)",
    "bmi":            "Body mass index",
    "waist_cm":       "Waist circumference",
    "age":            "Age",
    # Glucose
    "fasting_glucose":"Fasting blood glucose",
    "hba1c":          "HbA1c (average blood sugar)",
    # Lifestyle
    "avg_steps_k":    "Daily steps (thousands)",
    "avg_sleep":      "Average sleep duration",
    "smoking_current":"Current smoker",
    "smoking_ex":     "Ex-smoker",
    # Medical history
    "bp_medication":  "Blood pressure medication",
    "diabetes_existing": "Existing diabetes",
    "family_cvd":     "Family history of CVD",
    "family_diabetes":"Family history of diabetes",
    "sex_male":       "Biological sex (male)",
    # Imputation flags (should not dominate — penalise them lightly in SHAP display)
    "imp_total_chol": "Total cholesterol not measured",
    "imp_hdl_chol":   "HDL not measured",
    "imp_ldl_chol":   "LDL not measured",
    "imp_fasting_glucose": "Fasting glucose not measured",
    "imp_hba1c":      "HbA1c not measured",
    "imp_waist_cm":   "Waist not measured",
}


def format_safe_output(
    disease: str,
    raw_prob: Optional[float],
    shap_result: Optional[Dict],
    confidence: Dict[str, Any],
    bands: list,
    source: str,
    model_version: str,
    data_source: str,
    gate: Optional[str] = None,
    note: Optional[str] = None,
    sbp: float = 120,
    current_smoker: bool = False,
) -> SafeOutput:
    """
    Assemble a SafeOutput from raw model output + safety metadata.
    """
    if raw_prob is None or gate is not None:
        return SafeOutput(
            disease=disease, raw_probability=None,
            risk_band_label="—", risk_band_cat=note or "Insufficient data",
            color="gray",
            top_risk_factors=[], top_protective=[], counterfactuals=[],
            confidence_score=0, confidence_label="N/A", confidence_color="gray",
            warnings=confidence.get("warnings", []),
            limitations=confidence.get("limitations", []),
            referral=False,
            gate=gate, note=note,
            source=source, model_version=model_version, data_source=data_source,
        )

    band = _get_band(raw_prob if disease != "Cancer" else raw_prob, bands)

    # If confidence is VERY LOW, suppress numeric output
    if confidence["score"] < 40:
        band["label"] = "Estimate suppressed"
        band["category"] = "Confidence too low for numeric estimate"
        band["color"] = "gray"

    referral = referral_recommended(raw_prob * 100, confidence, sbp, current_smoker)

    return SafeOutput(
        disease=disease,
        raw_probability=round(raw_prob, 4),
        risk_band_label=band["label"],
        risk_band_cat=band["category"],
        color=band["color"],
        top_risk_factors=shap_result.get("top_risk_factors", []) if shap_result else [],
        top_protective=shap_result.get("top_protective", [])     if shap_result else [],
        counterfactuals=shap_result.get("counterfactuals", [])   if shap_result else [],
        confidence_score=confidence["score"],
        confidence_label=confidence["label"],
        confidence_color=confidence["color"],
        warnings=confidence["warnings"],
        limitations=confidence["limitations"],
        referral=referral,
        gate=gate, note=note,
        source=source, model_version=model_version, data_source=data_source,
    )
