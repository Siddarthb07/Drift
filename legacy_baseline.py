"""
Faithful *pre-fix* Drift behaviors for the baseline study arm.

This reconstructs the failure modes the honest engine removes:
  - race 'other'/unsupported → White PCE coefficients
  - silent waist = 94/80, SBP = 120, steps = 3000
  - under-40 framed as green 'low absolute risk'
  - point estimates, health-age hero, compounded cancer RR
  - engagement-style unlock ignored for scoring once profile exists

Pinned for evaluation — do not use as the product default.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from risk_calculators import (
    cancer_lifestyle_risk,
    estimate_health_age,
    findrisc_diabetes,
    pooled_cohort_cvd_10yr,
)


def _sf(v) -> Optional[float]:
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _mean(rows, col, default=0.0):
    vals = [r.get(col) for r in rows if r.get(col) is not None]
    return float(sum(vals) / len(vals)) if vals else default


def compute_legacy_baseline(user: Dict[str, Any], daily_rows: List[dict], labs: Dict[str, Any]) -> Dict[str, Any]:
    age = float(user.get("age") or 45)
    sex = str(user.get("sex") or user.get("sex_for_equation") or "male").lower()
    if sex not in ("male", "female"):
        sex = "male"
    height = float(user.get("height") or 170)
    weight = float(user.get("weight") or 70)
    bmi = weight / ((height / 100) ** 2) if height else 24
    # Silent defaults (the harm) — flags enable honesty-key scoring
    silent_waist = user.get("waist_cm") in (None, "", 0)
    silent_sbp = user.get("systolic") in (None, "", 0)
    waist = float(user.get("waist_cm") or (94 if sex == "male" else 80))
    sbp = float(user.get("systolic") or 120)
    race_raw = str(user.get("race") or "white").lower()
    # Silent White fallback
    race = race_raw if race_raw in ("white", "aa") else "white"

    smoker = str(user.get("smoking_status", "never")) == "current"
    ex_smoker = str(user.get("smoking_status", "never")) == "ex"
    bp_meds = bool(user.get("bp_medication"))
    diabetes = bool(user.get("existing_diabetes"))
    has_glucose_hx = bool(user.get("high_glucose_history"))
    family_diab = int(user.get("family_history_diabetes") or 0)
    family_cancer = bool(user.get("family_history_cancer"))
    alc = float(user.get("alcohol_per_week") or 0)

    avg_steps = _mean(daily_rows, "steps", 3000)
    avg_sleep = _mean(daily_rows, "sleep", 7)
    avg_stress = _mean(daily_rows, "stress_level", 5)
    active = avg_steps >= 7500 or _mean(daily_rows, "active_minutes", 0) >= (150 / 7)
    red_meat = _mean(daily_rows, "red_meat_servings", 2)
    processed = _mean(daily_rows, "processed_meat", 0) > 0
    veg_daily = _mean(daily_rows, "veg_servings", 0) >= 2 and _mean(daily_rows, "fruit_servings", 0) >= 1

    total_chol = _sf(labs.get("total_cholesterol"))
    hdl_chol = _sf(labs.get("hdl_cholesterol"))
    fasting_gl = _sf(labs.get("fasting_glucose"))
    hba1c = _sf(labs.get("hba1c"))

    results: Dict[str, Any] = {
        "_mode": "baseline",
        "_legacy": True,
        "_baseline_note": (
            "Legacy disclosure policies (White fallback, silent waist/SBP, green under-40, "
            "health-age, cancer RR). PCE *math* uses the corrected coefficients — "
            "transcription bugs are evaluated separately in Table 1."
        ),
    }

    if age < 40:
        results["CVD"] = {
            "risk_pct": None,
            "risk_category": "Under 40 — low absolute risk",
            "color": "green",
            "note": "ACC/AHA PCE is validated for ages 40–79. Focus on lifestyle factors.",
            "source": "ACC/AHA Pooled Cohort Equations",
            "equation": "PCE",
            "modifiable_factors": [],
            # No PCE compute → not a White-fallback event
            "legacy_white_fallback": False,
        }
    elif not total_chol or not hdl_chol:
        # Match pre-fix product: refuse CVD without cholesterol (do NOT invent 200/50).
        results["CVD"] = {
            "risk_pct": None,
            "risk_category": "Cholesterol labs needed",
            "color": "gray",
            "gate": "labs_cholesterol",
            "note": "Enter Total Cholesterol and HDL.",
            "equation": "PCE",
            "modifiable_factors": [],
            "legacy_white_fallback": False,
        }
    else:
        cvd = pooled_cohort_cvd_10yr(
            age, sex, total_chol, hdl_chol, sbp, bp_meds, smoker, diabetes, race
        )
        if cvd:
            cvd = dict(cvd)
            # Fallback only when PCE actually ran on a remapped race
            cvd["legacy_white_fallback"] = race_raw not in ("white", "aa")
            cvd["mapped_race"] = race
            cvd["silent_sbp_default"] = silent_sbp
            results["CVD"] = cvd
        else:
            results["CVD"] = {
                "risk_pct": None,
                "risk_category": "Unavailable",
                "color": "gray",
                "modifiable_factors": [],
                "legacy_white_fallback": False,
                "silent_sbp_default": silent_sbp,
            }

    # Under-40 path also used silent SBP if missing
    if "CVD" in results:
        results["CVD"] = dict(results["CVD"])
        results["CVD"].setdefault("silent_sbp_default", silent_sbp)

    diab = findrisc_diabetes(
        age, bmi, waist, sex, active, veg_daily, bp_meds, has_glucose_hx, family_diab
    )
    diab = dict(diab)
    diab["silent_waist_default"] = silent_waist
    results["Diabetes"] = diab

    canc = cancer_lifestyle_risk(
        age, bmi, sex, smoker, ex_smoker, alc, active, red_meat, processed, veg_daily, family_cancer
    )
    results["Cancer"] = canc

    results["_health_age"] = estimate_health_age(
        age, bmi, sbp, smoker, avg_sleep, avg_steps, avg_stress, total_chol, fasting_gl, hba1c
    )
    results["_trajectory"] = None
    results["_daily_count"] = len(daily_rows)
    results["_referral"] = {"recommended": False, "reasons": [], "message": ""}
    return results
