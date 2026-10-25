"""
Unified risk engine for Drift (honest default + baseline study arm).

Default CVD path: race-free PREVENT (all races/ethnicities).
Optional: PCE comparison only when race in {white, aa} and user opts in.
No silent waist/SBP/steps defaults. Score-specific gating (not 7-day unlock).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from disclosure import apply_disclosure, append_audit, lifestyle_trajectory
from legacy_baseline import compute_legacy_baseline
from prevent_equations import prevent_10yr
from risk_calculators import (
    PCE_VALID_RACES,
    cancer_lifestyle_risk,
    findrisc_diabetes,
    pooled_cohort_cvd_10yr,
)


def _sf(v) -> Optional[float]:
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _mean(rows: List[dict], col: str) -> Optional[float]:
    vals = [r.get(col) for r in rows if r.get(col) is not None]
    if not vals:
        return None
    return float(sum(vals) / len(vals))


def _refuse(category: str, note: str, gate: str, source: str = "") -> Dict[str, Any]:
    return {
        "risk_pct": None,
        "relative_risk": None,
        "risk_category": category,
        "color": "gray",
        "gate": gate,
        "refused": True,
        "note": note,
        "source": source,
        "modifiable_factors": [],
    }


def compute_risk_scores(
    user: Dict[str, Any],
    daily_rows: List[Dict[str, Any]],
    labs: Dict[str, Any],
    *,
    mode: str = "honest",
    username: str = "anon",
) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    mode = (mode or "honest").lower()
    if mode not in ("honest", "baseline"):
        mode = "honest"

    # Faithful legacy arm for FAccT comparison (separate code path).
    if mode == "baseline":
        legacy = compute_legacy_baseline(user, daily_rows, labs)
        for key in ("CVD", "Diabetes", "Cancer"):
            if key in legacy:
                legacy[key] = apply_disclosure(
                    legacy[key],
                    mode="baseline",
                    claim_id={
                        "CVD": "pce_ascvd",
                        "Diabetes": "findrisc",
                        "Cancer": "cancer_lifestyle_factors",
                    }[key],
                )
        if legacy.get("_health_age"):
            legacy["_health_age"] = apply_disclosure(
                legacy["_health_age"], mode="baseline", claim_id="health_age_heuristic"
            )
        append_audit(
            username=username,
            claim_id="legacy_baseline",
            decision="show",
            evidence_class="heuristic",
            inputs={"mode": "baseline"},
            mode="baseline",
            equation="legacy",
        )
        return legacy

    age = _sf(user.get("age"))
    sex_raw = str(user.get("sex") or "").lower()
    # Equation sex: PREVENT/PCE are binary. Prefer explicit sex_for_equation.
    sex_eq = str(user.get("sex_for_equation") or "").lower()
    if sex_eq not in ("male", "female"):
        sex_eq = sex_raw if sex_raw in ("male", "female") else ""

    height = _sf(user.get("height"))
    weight = _sf(user.get("weight"))
    waist = _sf(user.get("waist_cm"))
    sbp = _sf(user.get("systolic"))
    race = str(user.get("race") or "").lower() or None
    region = str(user.get("region") or "global").lower()
    prefer_pce = bool(user.get("prefer_pce")) or region in ("us_pce",)

    # Profile gate (shared)
    if not age or not height or not weight:
        for name, cid in [("CVD", "prevent_ascvd"), ("Diabetes", "findrisc"), ("Cancer", "cancer_lifestyle_factors")]:
            results[name] = apply_disclosure(
                _refuse(
                    "Profile incomplete",
                    "Enter age, height, and weight before any score is shown.",
                    "profile",
                ),
                mode=mode,
                claim_id=cid,
            )
        results["_trajectory"] = lifestyle_trajectory(daily_rows)
        results["_mode"] = mode
        return results

    bmi = weight / ((height / 100.0) ** 2) if height and weight else None
    smoker = str(user.get("smoking_status", "never")) == "current"
    ex_smoker = str(user.get("smoking_status", "never")) == "ex"
    bp_meds = bool(user.get("bp_medication"))
    statin = bool(user.get("statin") or user.get("on_statin"))
    diabetes = bool(user.get("existing_diabetes"))
    has_glucose_hx = bool(user.get("high_glucose_history"))
    family_diab = int(user.get("family_history_diabetes") or 0)
    family_cancer = bool(user.get("family_history_cancer"))
    alc = float(user.get("alcohol_per_week") or 0)

    avg_steps = _mean(daily_rows, "steps")
    avg_sleep = _mean(daily_rows, "sleep")
    avg_stress = _mean(daily_rows, "stress_level")
    avg_active = _mean(daily_rows, "active_minutes")
    red_meat = _mean(daily_rows, "red_meat_servings")
    processed = (_mean(daily_rows, "processed_meat") or 0) > 0
    veg_m = _mean(daily_rows, "veg_servings")
    fruit_m = _mean(daily_rows, "fruit_servings")

    # Activity: only True/False when we have evidence; else unknown
    if avg_steps is not None or avg_active is not None:
        physically_active = (avg_steps or 0) >= 7500 or (avg_active or 0) >= (150 / 7)
    else:
        physically_active = None

    if veg_m is not None and fruit_m is not None:
        veg_daily = veg_m >= 2 and fruit_m >= 1
    else:
        veg_daily = None

    total_chol = _sf(labs.get("total_cholesterol"))
    hdl_chol = _sf(labs.get("hdl_cholesterol"))
    fasting_gl = _sf(labs.get("fasting_glucose"))
    hba1c = _sf(labs.get("hba1c"))
    egfr = _sf(labs.get("egfr"))  # no silent 90 — PREVENT requires measured/entered eGFR

    # ── CVD ──────────────────────────────────────────────────
    cvd_source = "AHA PREVENT / ACC/AHA PCE"
    claim_id = "prevent_ascvd"
    if not sex_eq:
        cvd = _refuse(
            "Sex for equation not set",
            "PREVENT and PCE are sex-specific. Choose male or female for equation use, "
            "or we refuse a number rather than guess. Gender identity can differ.",
            "sex_equation",
            cvd_source,
        )
    elif not sbp:
        cvd = _refuse(
            "Blood pressure required",
            "Systolic BP was not entered. We do not invent 120 mmHg.",
            "missing_sbp",
            cvd_source,
        )
    elif not total_chol or not hdl_chol:
        cvd = _refuse(
            "Cholesterol labs needed",
            "Enter total cholesterol and HDL. Missing labs are not median-imputed.",
            "labs_cholesterol",
            cvd_source,
        )
    elif egfr is None:
        cvd = _refuse(
            "eGFR required for PREVENT",
            "Kidney function (eGFR) was not entered. We do not invent eGFR=90.",
            "missing_egfr",
            cvd_source,
        )
    elif bmi is None or bmi <= 0:
        cvd = _refuse(
            "Height/weight required",
            "BMI could not be computed. Enter height and weight.",
            "missing_bmi",
            cvd_source,
        )
    elif age < 30:
        cvd = _refuse(
            "Age under 30 — not estimated",
            "PREVENT is validated for ages 30–79. Under-30 is not shown as 'low risk'.",
            "age_range",
            cvd_source,
        )
    elif age > 79:
        cvd = _refuse(
            "Age over 79 — not estimated",
            "Published equations are not validated above 79 in this tool.",
            "age_range",
            cvd_source,
        )
    else:
        use_pce = prefer_pce and race in PCE_VALID_RACES and age >= 40
        if use_pce:
            raw = pooled_cohort_cvd_10yr(
                age, sex_eq, total_chol, hdl_chol, sbp, bp_meds, smoker, diabetes, race
            )
            claim_id = "pce_ascvd"
        else:
            raw = prevent_10yr(
                sex=sex_eq,
                age=age,
                total_chol=total_chol,
                hdl_chol=hdl_chol,
                sbp=sbp,
                diabetes=diabetes,
                current_smoker=smoker,
                bmi=bmi,
                egfr=egfr,
                bp_treated=bp_meds,
                statin=statin,
                outcome="ascvd",
            )
            claim_id = "prevent_ascvd"
            if prefer_pce and race and race not in PCE_VALID_RACES and raw:
                raw = dict(raw)
                raw["note"] = (
                    (raw.get("note") or "")
                    + " PCE was requested but is not validated for your selected "
                    "race/ethnicity — showing race-free PREVENT instead (no White fallback)."
                )

        if not raw:
            cvd = _refuse(
                "Could not compute",
                "Inputs out of equation range.",
                "compute_fail",
                cvd_source,
            )
            claim_id = "prevent_ascvd"
        else:
            cvd = dict(raw)
            cvd["race"] = race
            cvd["age"] = age
            if bmi is not None and not (18.5 <= bmi <= 39.9):
                cvd["bmi_out_of_published_range"] = True
                cvd["note"] = (
                    (cvd.get("note") or "")
                    + " BMI is outside the published PREVENT calculator range (18.5–39.9); "
                    "ASCVD base-model BMI coefficients are zero — estimate shown with coverage caveat."
                ).strip()
            if claim_id == "prevent_ascvd" and race in PCE_VALID_RACES and age >= 40:
                pce = pooled_cohort_cvd_10yr(
                    age, sex_eq, total_chol, hdl_chol, sbp, bp_meds, smoker, diabetes, race
                )
                if pce:
                    cvd["comparison_pce"] = {
                        "risk_pct": pce["risk_pct"],
                        "risk_category": pce["risk_category"],
                        "note": "Optional PCE comparison (race-stratified, US White/AA only).",
                    }

    # Ensure refused path also carries race/age for claim predicates
    if isinstance(cvd, dict):
        cvd.setdefault("race", race)
        cvd.setdefault("age", age)

    results["CVD"] = apply_disclosure(cvd, mode=mode, claim_id=claim_id)
    append_audit(
        username=username,
        claim_id=claim_id,
        decision="refuse" if results["CVD"].get("refused") else "show",
        evidence_class=results["CVD"].get("evidence_class", "published_equation"),
        inputs={"age": age, "sex": sex_eq, "race": race, "sbp": sbp, "tc": total_chol},
        mode=mode,
        equation=results["CVD"].get("equation"),
    )

    # ── Diabetes FINDRISC ────────────────────────────────────
    if physically_active is None or veg_daily is None:
        diab = _refuse(
            "Lifestyle inputs incomplete",
            "FINDRISC needs activity and fruit/veg habits. Log daily data or answer the survey — "
            "we do not invent steps or diet.",
            "lifestyle_missing",
            "FINDRISC",
        )
    elif not sex_eq:
        diab = _refuse(
            "Sex for equation not set",
            "FINDRISC waist thresholds are sex-specific.",
            "sex_equation",
            "FINDRISC",
        )
    else:
        if waist is None:
            # Interval over waist points 0/3/4 without inventing a waist
            scores = []
            for w_proxy in (
                70 if sex_eq == "female" else 80,
                85 if sex_eq == "female" else 98,
                95 if sex_eq == "female" else 110,
            ):
                scores.append(
                    findrisc_diabetes(
                        age, bmi, w_proxy, sex_eq, physically_active, veg_daily,
                        bp_meds, has_glucose_hx, family_diab,
                    )["score"]
                )
            lo, hi = min(scores), max(scores)
            # Map interval to categories via mid score display
            mid = findrisc_diabetes(
                age, bmi, (70 if sex_eq == "female" else 80), sex_eq,
                physically_active, veg_daily, bp_meds, has_glucose_hx, family_diab,
            )
            diab = {
                "score": None,
                "score_range": [lo, hi],
                "max_score": 26,
                "risk_pct": None,
                "risk_category": f"FINDRISC {lo}–{hi}/26 (waist unmeasured)",
                "color": "yellow",
                "source": mid["source"],
                "note": (
                    "Waist circumference was not entered. Showing a score interval across "
                    "plausible waist bands instead of silently adding +3 points at the cutoff."
                ),
                "modifiable_factors": mid.get("modifiable_factors", []),
                "inputs_omitted": ["waist_cm"],
            }
            # For baseline mode, still don't invent waist — keep interval
        else:
            diab = findrisc_diabetes(
                age, bmi, waist, sex_eq, physically_active, veg_daily,
                bp_meds, has_glucose_hx, family_diab,
            )
            diab["inputs_omitted"] = []

        if fasting_gl and fasting_gl >= 100:
            diab["note"] = (diab.get("note") or "") + (
                f" Fasting glucose {fasting_gl} mg/dL is in the prediabetes range — discuss with a clinician."
            )
        elif hba1c and hba1c >= 5.7:
            diab["note"] = (diab.get("note") or "") + (
                f" HbA1c {hba1c}% is in the prediabetes range — discuss with a clinician."
            )

    results["Diabetes"] = apply_disclosure(diab, mode=mode, claim_id="findrisc")

    # ── Cancer: factors only in honest mode ──────────────────
    if red_meat is None:
        red_meat_v = 0.0
        meat_note = " Red meat intake not logged — treated as unknown (no penalty invented)."
    else:
        red_meat_v = red_meat
        meat_note = ""

    if mode == "baseline":
        canc = cancer_lifestyle_risk(
            age, bmi, sex_eq or "male", smoker, ex_smoker, alc,
            bool(physically_active), red_meat_v, processed,
            bool(veg_daily), family_cancer,
        )
    else:
        # Only list factors we actually observed — no invented inactivity/diet penalties.
        if physically_active is None or veg_daily is None or sex_eq == "":
            canc = _refuse(
                "Lifestyle inputs incomplete",
                "Cancer factor card needs activity and diet logs (and equation sex). "
                "We do not invent inactivity or diet scores.",
                "lifestyle_missing",
                "WCRF/IARC factor list",
            )
        else:
            canc = cancer_lifestyle_risk(
                age, bmi, sex_eq, smoker, ex_smoker, alc,
                physically_active, red_meat_v, processed, veg_daily, family_cancer,
            )
            canc["relative_risk"] = None
            canc["risk_category"] = "Lifestyle factors (no combined RR)"
            canc["color"] = "yellow"
            canc["note"] = (
                "Individual lifestyle factors associated with cancer risk (WCRF/IARC). "
                "No single multi-cancer absolute probability is shown." + meat_note
            )

    results["Cancer"] = apply_disclosure(canc, mode=mode, claim_id="cancer_lifestyle_factors")

    results["_trajectory"] = apply_disclosure(
        lifestyle_trajectory(daily_rows), mode=mode, claim_id="lifestyle_trajectory"
    )
    results["_health_age"] = None
    results["_daily_count"] = len(daily_rows)
    results["_mode"] = mode
    results["_bmi"] = round(bmi, 1) if bmi else None
    results["_equation_sex"] = sex_eq or None
    results["_race"] = race
    results["_referral"] = _referral_flag(results, sbp, smoker)
    return results


def _referral_flag(results: Dict[str, Any], sbp: Optional[float], smoker: bool) -> Dict[str, Any]:
    reasons = []
    cvd = results.get("CVD") or {}
    if cvd.get("risk_pct_exact") and cvd["risk_pct_exact"] >= 15:
        reasons.append("Estimated CVD band includes ≥15% territory")
    if cvd.get("color") == "red":
        reasons.append("High CVD category")
    if sbp and sbp >= 180:
        reasons.append("Systolic BP ≥180 mmHg — seek urgent care")
    if smoker:
        reasons.append("Current smoking — cessation support recommended")
    diab = results.get("Diabetes") or {}
    if diab.get("color") == "red":
        reasons.append("High FINDRISC category")
    return {
        "recommended": bool(reasons),
        "reasons": reasons,
        "message": (
            "Consider discussing these results with a clinician. "
            "This tool does not diagnose or prescribe."
            if reasons else ""
        ),
    }
