"""
Race-free AHA PREVENT equations (Khan et al., Circulation 2024).

Coefficients ported from the open PyPREVENT reference implementation
(https://github.com/lhegstrom/PyPrevent), which encodes the published
Supplemental Table S12 simplified forms.

Default CVD path for Drift: usable for all races/ethnicities without
routing non-White/non-AA users through White PCE coefficients.
Sex is still binary because PREVENT is sex-specific; Drift refuses a
point estimate when sex_for_equation is unavailable.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class _Covariates:
    constant: float
    diabetes_factor: float
    smoker_factor: float
    htn_meds_factor: float
    cholesterol_meds_factor: float
    age_adjustment_factor: float
    age_squared_factor: float
    cholesterol_base_multiplier: float
    total_cholesterol_diff_factor: float
    hdl_cholesterol_diff_factor: float
    systolic_bp_min_factor: float
    systolic_bp_max_factor: float
    egfr_max_factor: float
    egfr_min_factor: float
    htn_meds_systolic_bp_max_factor: float
    cholesterol_meds_cholesterol_diff_factor: float
    age_adjustment_cholesterol_diff_factor: float
    age_adjustment_hdl_cholesterol_diff_factor: float
    age_adjustment_systolic_bp_max_factor: float
    age_min_egfr_factor: float
    diabetes_age_factor: float
    smoker_age_factor: float
    bmi_min_factor: float
    bmi_max_factor: float
    age_bmi_max_factor: float


_FEMALE_10_ASCVD = _Covariates(
    -3.819975, 0.8348585, 0.4831078, 0.2265309, -0.0592374, 0.719883, 0.0,
    0.02586, 0.1176967, -0.151185, -0.0835358, 0.3592852, 0.0397779, 0.4864619,
    -0.0395762, 0.0844423, -0.0567839, 0.0325692, -0.1035985, -0.1671492,
    -0.2417542, -0.0791142, 0.0, 0.0, 0.0,
)
_MALE_10_ASCVD = _Covariates(
    -3.500655, 0.7189597, 0.3956973, 0.2036522, -0.0865581, 0.7099847, 0.0,
    0.02586, 0.1658663, -0.1144285, -0.2837212, 0.3239977, 0.0203619, 0.3690075,
    -0.0322916, 0.114563, -0.0300005, 0.0232747, -0.0927024, -0.1217081,
    -0.2018525, -0.0970527, 0.0, 0.0, 0.0,
)
_FEMALE_10_CVD = _Covariates(
    -3.307728, 0.8667604, 0.5360739, 0.3151672, -0.1477655, 0.7939329, 0.0,
    0.02586, 0.0305239, -0.1606857, -0.2394003, 0.3600781, 0.0433769, 0.6045917,
    -0.0663612, 0.1197879, -0.0819715, 0.0306769, -0.0946348, -0.1637806,
    -0.27057, -0.078715, 0.0, 0.0, 0.0,
)
_MALE_10_CVD = _Covariates(
    -3.031168, 0.7692857, 0.4386871, 0.288879, -0.1337349, 0.7688528, 0.0,
    0.02586, 0.0736174, -0.0954431, -0.4347345, 0.3362658, 0.0164827, 0.5378979,
    -0.0475924, 0.150273, -0.0517874, 0.0191169, -0.1049477, -0.1543702,
    -0.2251948, -0.0895067, 0.0, 0.0, 0.0,
)


def _linear_predictor(
    cov: _Covariates,
    *,
    has_diabetes: bool,
    current_smoker: bool,
    on_htn_meds: bool,
    on_cholesterol_meds: bool,
    systolic_bp: float,
    cholesterol_diff: float,
    hdl_cholesterol: float,
    adjusted_age: float,
    adjusted_age_squared: float,
    egfr: float,
    bmi: float,
) -> float:
    diabetes_factor = cov.diabetes_factor if has_diabetes else 0.0
    smoker_factor = cov.smoker_factor if current_smoker else 0.0
    htn_meds_factor = cov.htn_meds_factor if on_htn_meds else 0.0
    chol_meds_factor = cov.cholesterol_meds_factor if on_cholesterol_meds else 0.0
    sbp_adj_max = (max(systolic_bp, 110.0) - 130.0) / 20.0
    sbp_adj_min = (min(systolic_bp, 110.0) - 110.0) / 20.0
    chol_diff_term = cov.cholesterol_base_multiplier * cholesterol_diff - 3.5
    hdl_term = (cov.cholesterol_base_multiplier * hdl_cholesterol - 1.3) / 0.3
    egfr_adj_min = (min(egfr, 60.0) - 60.0) / -15.0
    egfr_adj_max = (max(egfr, 60.0) - 90.0) / -15.0
    bmi_adj_min = (min(bmi, 30.0) - 25.0) / 5.0
    bmi_adj_max = (max(bmi, 30.0) - 30.0) / 5.0
    diabetes_age = cov.diabetes_age_factor * adjusted_age if has_diabetes else 0.0
    smoker_age = cov.smoker_age_factor * adjusted_age if current_smoker else 0.0
    return sum([
        cov.age_adjustment_factor * adjusted_age,
        cov.age_squared_factor * adjusted_age_squared,
        cov.constant,
        cov.total_cholesterol_diff_factor * chol_diff_term,
        cov.hdl_cholesterol_diff_factor * hdl_term,
        cov.systolic_bp_min_factor * sbp_adj_min,
        cov.systolic_bp_max_factor * sbp_adj_max,
        diabetes_factor,
        smoker_factor,
        cov.egfr_min_factor * egfr_adj_min,
        cov.egfr_max_factor * egfr_adj_max,
        htn_meds_factor,
        chol_meds_factor,
        cov.htn_meds_systolic_bp_max_factor * sbp_adj_max if on_htn_meds else 0.0,
        cov.cholesterol_meds_cholesterol_diff_factor * chol_diff_term if on_cholesterol_meds else 0.0,
        cov.age_adjustment_cholesterol_diff_factor * adjusted_age * chol_diff_term,
        cov.age_adjustment_hdl_cholesterol_diff_factor * adjusted_age * hdl_term,
        cov.age_adjustment_systolic_bp_max_factor * adjusted_age * sbp_adj_max,
        diabetes_age,
        smoker_age,
        cov.age_min_egfr_factor * adjusted_age * egfr_adj_min,
        cov.bmi_min_factor * bmi_adj_min,
        cov.bmi_max_factor * bmi_adj_max,
        cov.age_bmi_max_factor * adjusted_age * bmi_adj_max,
    ])


def _risk_pct(lp: float) -> float:
    # Simplified logistic form used by PyPREVENT / S12 approximations.
    return (math.exp(lp) / (1.0 + math.exp(lp))) * 100.0


def prevent_10yr(
    *,
    sex: str,
    age: float,
    total_chol: float,
    hdl_chol: float,
    sbp: float,
    diabetes: bool,
    current_smoker: bool,
    bmi: float,
    egfr: float,
    bp_treated: bool,
    statin: bool = False,
    outcome: str = "ascvd",
) -> Optional[Dict[str, Any]]:
    """
    10-year PREVENT risk (race-free). Ages 30–79.
    outcome: 'ascvd' (default for Drift UI) or 'cvd' (total CVD incl. HF).
    """
    sex_l = sex.lower()
    if sex_l not in ("male", "female"):
        return None
    if not (30 <= age <= 79):
        return None
    if total_chol <= 0 or hdl_chol <= 0 or sbp <= 0 or bmi <= 0 or egfr is None:
        return None
    # Hard refuse outside published calculator input ranges (no silent clamp).
    tc, hdl, sbp_v, bmi_v, egfr_v = (
        float(total_chol), float(hdl_chol), float(sbp), float(bmi), float(egfr),
    )
    if not (130.0 <= tc <= 320.0):
        return None
    if not (20.0 <= hdl <= 100.0):
        return None
    if not (90.0 <= sbp_v <= 200.0):
        return None
    # ASCVD base-model BMI coefficients are 0.0 (Khan/PyPREVENT); do not refuse on BMI alone.
    # Total-CVD / HF forms use BMI — keep published range there.
    if outcome != "ascvd" and not (18.5 <= bmi_v <= 39.9):
        return None
    if bmi_v <= 0:
        return None
    if not (15.0 <= egfr_v <= 140.0):
        return None

    adjusted_age = (age - 55.0) / 10.0
    adjusted_age_sq = adjusted_age ** 2
    chol_diff = tc - hdl

    if outcome == "cvd":
        cov = _FEMALE_10_CVD if sex_l == "female" else _MALE_10_CVD
        label = "Total CVD (ASCVD + HF)"
    else:
        cov = _FEMALE_10_ASCVD if sex_l == "female" else _MALE_10_ASCVD
        label = "ASCVD"

    lp = _linear_predictor(
        cov,
        has_diabetes=diabetes,
        current_smoker=current_smoker,
        on_htn_meds=bp_treated,
        on_cholesterol_meds=statin,
        systolic_bp=sbp_v,
        cholesterol_diff=chol_diff,
        hdl_cholesterol=hdl,
        adjusted_age=adjusted_age,
        adjusted_age_squared=adjusted_age_sq,
        egfr=egfr_v,
        bmi=bmi_v,
    )
    risk_pct = round(max(0.0, min(100.0, _risk_pct(lp))), 1)

    if risk_pct < 5:
        category, color = "Low (<5%)", "green"
    elif risk_pct < 7.5:
        category, color = "Borderline (5–7.5%)", "yellow"
    elif risk_pct < 20:
        category, color = "Intermediate (7.5–20%)", "orange"
    else:
        category, color = "High (≥20%)", "red"

    return {
        "risk_pct": risk_pct,
        "risk_category": category,
        "color": color,
        "equation": "PREVENT",
        "outcome": outcome,
        "outcome_label": label,
        "race_free": True,
        "source": "AHA PREVENT (Khan et al., Circulation 2024) — race-free sex-specific equations",
        "note": (
            f"10-year {label} risk. Race/ethnicity is not an input — intentional design so the "
            "same equation applies across racial groups. Validated mainly in US adults 30–79 without "
            "prior CVD. Educational estimate only; not a diagnosis."
        ),
        "inputs_used": {
            "age": age, "sex": sex_l, "total_chol": tc, "hdl": hdl, "sbp": sbp_v,
            "bmi": bmi_v, "egfr": egfr_v, "diabetes": diabetes, "smoker": current_smoker,
            "bp_treated": bp_treated, "statin": statin,
        },
        "modifiable_factors": [],
    }
