"""
Evidence-Based Clinical Risk Calculators — HealthTracker v5
============================================================

CVD:
  2013 ACC/AHA Pooled Cohort Equations (PCE)
  Goff DC Jr et al. Circulation. 2014;129(25 Suppl 2):S49-73.
  DOI: 10.1161/01.cir.0000437741.48606.98

Diabetes (Type 2):
  Finnish Diabetes Risk Score — FINDRISC
  Lindström J, Tuomilehto J. Diabetes Care. 2003;26(3):725-31.
  DOI: 10.2337/diacare.26.3.725

Cancer Lifestyle Risk Indicator:
  WCRF/AICR Third Expert Report — Diet, Nutrition, Physical Activity and Cancer, 2018.
  NCI Cancer Risk Factor Magnitude Reviews (published meta-analyses).
  NOTE: this is a RELATIVE RISK indicator, not an absolute probability tool.
  No single validated score exists for all cancers; this tool is educational only.

DISCLAIMER: All outputs are estimates for informational purposes only.
They are NOT a substitute for clinical evaluation by a qualified healthcare provider.
"""

import math
from typing import Optional


# ─────────────────────────────────────────────────────────────
# CVD — Pooled Cohort Equations (ACC/AHA 2013)
# ─────────────────────────────────────────────────────────────

def pooled_cohort_cvd_10yr(
    age: float,
    sex: str,             # 'male' or 'female'
    total_chol: float,    # mg/dL
    hdl_chol: float,      # mg/dL
    sbp: float,           # systolic BP mmHg
    bp_treated: bool,     # currently on BP medication
    current_smoker: bool,
    diabetes: bool,
    race: str = "white"   # 'white' or 'aa' (African American)
) -> Optional[dict]:
    """
    10-year ASCVD risk. Valid for ages 40-79.
    Returns None if inputs are out of valid range.
    """
    if not (40 <= age <= 79):
        return None
    if total_chol <= 0 or hdl_chol <= 0 or sbp <= 0:
        return None

    try:
        ln_age  = math.log(age)
        ln_tc   = math.log(total_chol)
        ln_hdl  = math.log(hdl_chol)
        ln_sbp_t  = math.log(sbp) if bp_treated  else 0.0
        ln_sbp_u  = math.log(sbp) if not bp_treated else 0.0
        smoke   = 1.0 if current_smoker else 0.0
        diab    = 1.0 if diabetes else 0.0

        if sex.lower() == "female":
            if race == "aa":
                l = (17.1141 * ln_age + 0.9396 * ln_tc
                     - 18.9196 * ln_hdl + 4.4748 * ln_age * ln_hdl
                     + 29.2907 * ln_sbp_t - 6.4321 * ln_age * ln_sbp_t
                     + 27.8197 * ln_sbp_u - 6.0873 * ln_age * ln_sbp_u
                     + 0.8738 * smoke + 0.8738 * diab)
                baseline, mean_l = 0.9533, 86.6081
            else:   # white / default
                l = (-29.799 + 4.884 * ln_age
                     + 13.540 * ln_tc  - 3.114  * ln_hdl
                     + 2.019  * ln_sbp_t + 1.957 * ln_sbp_u
                     + 7.574  * smoke   + 0.661  * diab)
                baseline, mean_l = 0.9665, 26.1931
        else:   # male
            if race == "aa":
                l = (2.469  * ln_age + 0.302  * ln_tc
                     - 0.307 * ln_hdl
                     + 1.916 * ln_sbp_t + 1.809 * ln_sbp_u
                     + 0.549 * smoke    + 0.645 * diab)
                baseline, mean_l = 0.8954, 19.5425
            else:   # white / default
                l = (12.344 * ln_age + 11.853 * ln_tc
                     - 2.664 * ln_age * ln_tc
                     - 7.990 * ln_hdl  + 1.769 * ln_age * ln_hdl
                     + 1.764 * ln_sbp_t + 1.797 * ln_sbp_u
                     + 7.837 * smoke    - 1.795 * ln_age * smoke
                     + 0.658 * diab)
                baseline, mean_l = 0.9144, 61.1816

        risk = 1.0 - baseline ** math.exp(l - mean_l)
        risk = max(0.0, min(1.0, risk))

        # Risk category (ACC/AHA thresholds)
        if risk < 0.05:
            category, color = "Low (<5%)", "green"
        elif risk < 0.075:
            category, color = "Borderline (5–7.5%)", "yellow"
        elif risk < 0.20:
            category, color = "Intermediate (7.5–20%)", "orange"
        else:
            category, color = "High (≥20%)", "red"

        missing_labs = []
        return {
            "risk_pct": round(risk * 100, 1),
            "risk_category": category,
            "color": color,
            "source": "ACC/AHA Pooled Cohort Equations (Goff et al., Circulation 2014)",
            "note": "10-year risk of first atherosclerotic cardiovascular event",
            "modifiable_factors": _cvd_modifiable(current_smoker, total_chol, hdl_chol, sbp, bp_treated, diabetes)
        }
    except (ValueError, ZeroDivisionError):
        return None


def _cvd_modifiable(smoker, total_chol, hdl_chol, sbp, bp_treated, diabetes):
    factors = []
    if smoker:
        factors.append({"factor": "Current smoker", "impact": "Very high", "action": "Quit smoking — largest single modifiable CVD risk factor"})
    if total_chol and total_chol >= 240:
        factors.append({"factor": "High total cholesterol", "impact": "High", "action": "Discuss statin therapy; dietary changes"})
    elif total_chol and total_chol >= 200:
        factors.append({"factor": "Borderline cholesterol", "impact": "Moderate", "action": "Reduce saturated fat; increase fiber"})
    if hdl_chol and hdl_chol < 40:
        factors.append({"factor": "Low HDL ('good') cholesterol", "impact": "High", "action": "Increase aerobic exercise; reduce trans fats"})
    if sbp and sbp >= 140:
        factors.append({"factor": "Stage 2 hypertension", "impact": "Very high", "action": "Medical evaluation; DASH diet; sodium restriction"})
    elif sbp and sbp >= 130:
        factors.append({"factor": "Elevated blood pressure", "impact": "High", "action": "Lifestyle modification; possible medication review"})
    if diabetes:
        factors.append({"factor": "Diabetes", "impact": "High", "action": "Optimal glucose control significantly reduces CVD risk"})
    return factors


# ─────────────────────────────────────────────────────────────
# Type 2 Diabetes — FINDRISC
# ─────────────────────────────────────────────────────────────

def findrisc_diabetes(
    age: float,
    bmi: float,
    waist_cm: float,
    sex: str,
    physically_active: bool,      # ≥30 min moderate activity most days
    eats_veg_fruit_daily: bool,
    bp_medication: bool,
    high_glucose_history: bool,   # ever told blood glucose was high
    family_history: int           # 0=none, 1=2nd-degree rel, 2=parent/sibling/child
) -> dict:
    """
    Finnish Diabetes Risk Score (FINDRISC). Max score = 26.
    Validated to predict 10-year T2D risk in European populations.
    """
    score = 0

    # Age points
    if   age < 45: score += 0
    elif age < 55: score += 2
    elif age < 65: score += 3
    else:          score += 4

    # BMI points
    if   bmi < 25: score += 0
    elif bmi < 30: score += 1
    else:          score += 3

    # Waist circumference points (sex-specific)
    if sex.lower() == "male":
        if   waist_cm < 94:  score += 0
        elif waist_cm < 102: score += 3
        else:                score += 4
    else:
        if   waist_cm < 80:  score += 0
        elif waist_cm < 88:  score += 3
        else:                score += 4

    if not physically_active:   score += 2
    if not eats_veg_fruit_daily: score += 1
    if bp_medication:            score += 2
    if high_glucose_history:     score += 5
    if   family_history == 1:    score += 3
    elif family_history >= 2:    score += 5

    # Score-to-risk mapping (FINDRISC validation study)
    if   score < 7:   risk, category, color = 0.01, "Low",              "green"
    elif score < 12:  risk, category, color = 0.04, "Slightly elevated","yellow"
    elif score < 15:  risk, category, color = 0.17, "Moderate",         "orange"
    elif score < 21:  risk, category, color = 0.33, "High",             "red"
    else:             risk, category, color = 0.50, "Very high",        "red"

    return {
        "score": score,
        "max_score": 26,
        "risk_pct": round(risk * 100, 1),
        "risk_category": category,
        "color": color,
        "source": "FINDRISC — Lindström & Tuomilehto, Diabetes Care 2003",
        "note": "10-year risk of developing Type 2 diabetes",
        "modifiable_factors": _diabetes_modifiable(bmi, waist_cm, sex, physically_active, eats_veg_fruit_daily, bp_medication)
    }


def _diabetes_modifiable(bmi, waist_cm, sex, active, veg, bp_meds):
    factors = []
    if bmi >= 30:
        factors.append({"factor": "Obesity", "impact": "Very high", "action": "Even 5–7% weight loss reduces T2D risk by ~58% (DPP trial)"})
    elif bmi >= 25:
        factors.append({"factor": "Overweight", "impact": "High", "action": "Weight reduction through diet and exercise"})
    risk_waist = (sex.lower() == "male" and waist_cm >= 94) or (sex.lower() == "female" and waist_cm >= 80)
    if risk_waist:
        factors.append({"factor": "Elevated waist circumference", "impact": "High", "action": "Reduce abdominal fat through aerobic exercise and calorie reduction"})
    if not active:
        factors.append({"factor": "Physical inactivity", "impact": "High", "action": "150 min/week of moderate exercise (brisk walking) reduces T2D risk by 30–40%"})
    if not veg:
        factors.append({"factor": "Low fruit/vegetable intake", "impact": "Moderate", "action": "Increase fiber and micronutrient intake; reduces glycemic load"})
    return factors


# ─────────────────────────────────────────────────────────────
# Cancer Lifestyle Risk Indicator
# ─────────────────────────────────────────────────────────────

def cancer_lifestyle_risk(
    age: float,
    bmi: float,
    sex: str,
    current_smoker: bool,
    ex_smoker: bool,
    alcohol_drinks_per_week: float,
    physically_active: bool,           # ≥150 min/week moderate
    red_meat_servings_per_week: float,
    processed_meat: bool,
    fruit_veg_daily: bool,
    family_history_cancer: bool
) -> dict:
    """
    Lifestyle-based cancer relative risk indicator.

    Uses relative risk (RR) multipliers from:
    - WCRF/AICR Expert Report 2018 (diet, activity, obesity)
    - IARC Monographs on tobacco and alcohol
    - NCI PDQ® Cancer Prevention meta-analyses

    Returns relative risk vs. an average-lifestyle person of the same age,
    NOT an absolute probability. Cancer is highly heterogeneous; no single
    validated score covers all types. This tool is educational only.
    """
    rr = 1.0
    factors = []

    # Smoking (IARC Group 1 carcinogen, 13+ cancer types)
    if current_smoker:
        rr *= 2.0
        factors.append({"factor": "Current smoker", "impact": "Very high ↑", "rr_contrib": 2.0,
                         "action": "Quitting is the single most impactful cancer-prevention action"})
    elif ex_smoker:
        rr *= 1.25
        factors.append({"factor": "Ex-smoker", "impact": "Elevated ↑", "rr_contrib": 1.25,
                         "action": "Risk continues to decline with years since quitting"})

    # Obesity (13 cancer types — IARC 2016)
    if bmi >= 30:
        rr *= 1.32
        factors.append({"factor": "Obesity (BMI ≥ 30)", "impact": "High ↑", "rr_contrib": 1.32,
                         "action": "Weight loss reduces risk for at least 13 cancer types"})
    elif bmi >= 25:
        rr *= 1.13
        factors.append({"factor": "Overweight (BMI 25–30)", "impact": "Moderate ↑", "rr_contrib": 1.13,
                         "action": "Even modest weight reduction is beneficial"})

    # Alcohol (IARC Group 1, dose-dependent across 7 cancer types)
    weekly_g = alcohol_drinks_per_week * 14.0   # 1 US drink ≈ 14 g ethanol
    daily_g  = weekly_g / 7.0
    alc_rr   = 1.0 + (daily_g / 10.0) * 0.07   # ~7% per 10 g/day
    alc_rr   = min(alc_rr, 2.0)
    if alcohol_drinks_per_week > 7:
        rr *= alc_rr
        factors.append({"factor": f"Alcohol ({alcohol_drinks_per_week:.0f} drinks/week)", "impact": "Moderate ↑", "rr_contrib": round(alc_rr, 2),
                         "action": "Limiting alcohol to ≤1 drink/day substantially lowers risk"})
    elif alcohol_drinks_per_week > 0:
        rr *= alc_rr   # small effect, no recommendation triggered

    # Physical inactivity (convincing evidence: colon, breast, endometrial)
    if not physically_active:
        rr *= 1.20
        factors.append({"factor": "Physical inactivity", "impact": "Moderate ↑", "rr_contrib": 1.20,
                         "action": "150–300 min/week moderate activity reduces risk by 10–20%"})
    else:
        rr *= 0.92

    # Red meat ≥5 servings/week (WCRF: convincing for colorectal)
    if red_meat_servings_per_week >= 5:
        rr *= 1.18
        factors.append({"factor": "High red meat intake", "impact": "Moderate ↑", "rr_contrib": 1.18,
                         "action": "Limit red meat to <500 g/week; colorectal cancer link is strongest"})
    elif red_meat_servings_per_week >= 3:
        rr *= 1.08

    # Processed meat (IARC Group 1 for colorectal cancer)
    if processed_meat:
        rr *= 1.16
        factors.append({"factor": "Regular processed meat", "impact": "Moderate ↑", "rr_contrib": 1.16,
                         "action": "Minimise bacon, sausages, hot dogs — each 50 g/day raises colorectal risk ~18%"})

    # Fruit & veg (protective, mainly digestive cancers)
    if fruit_veg_daily:
        rr *= 0.90
    else:
        rr *= 1.05
        factors.append({"factor": "Low fruit & vegetable intake", "impact": "Low–moderate ↑", "rr_contrib": 1.05,
                         "action": "Aim for 5+ portions/day; fibre and phytochemicals are protective"})

    # Family history (general, not gene-specific)
    if family_history_cancer:
        rr *= 1.75
        factors.append({"factor": "Family history of cancer", "impact": "High ↑ (non-modifiable)", "rr_contrib": 1.75,
                         "action": "Discuss earlier/more frequent screening with your doctor"})

    # Summary lifestyle score (0–100, protective factors)
    protective = sum([
        not current_smoker and not ex_smoker,
        bmi < 25,
        alcohol_drinks_per_week <= 7,
        physically_active,
        red_meat_servings_per_week < 3,
        not processed_meat,
        fruit_veg_daily
    ])
    lifestyle_score = int((protective / 7) * 100)

    if   rr < 0.85:  category, color = "Below population average",       "green"
    elif rr < 1.30:  category, color = "Near population average",         "yellow"
    elif rr < 1.80:  category, color = "Moderately above average",        "orange"
    elif rr < 2.50:  category, color = "Substantially elevated",          "red"
    else:            category, color = "Markedly elevated",               "red"

    return {
        "relative_risk": round(rr, 2),
        "risk_category": category,
        "color": color,
        "lifestyle_score": lifestyle_score,
        "modifiable_factors": [f for f in factors if "non-modifiable" not in f.get("impact","")],
        "all_factors": factors,
        "source": "WCRF/AICR Expert Report 2018; IARC Monographs; NCI PDQ® Reviews",
        "note": "Relative risk vs. average lifestyle (not an absolute probability). Covers lifestyle-associated cancers; family history and genetics may dominate individual risk."
    }


# ─────────────────────────────────────────────────────────────
# Lab Reference Ranges
# ─────────────────────────────────────────────────────────────

LAB_REFS = {
    "total_cholesterol":  {"unit": "mg/dL",  "optimal": (0, 200),       "borderline": (200, 240),  "high": (240, 9999),  "note": "Lower is better"},
    "ldl_cholesterol":    {"unit": "mg/dL",  "optimal": (0, 100),       "borderline": (100, 160),  "high": (160, 9999),  "note": "Lower is better (aim <70 in high CVD risk)"},
    "hdl_cholesterol":    {"unit": "mg/dL",  "optimal_m": (40, 9999),   "optimal_f": (50, 9999),   "protective": (60, 9999), "note": "Higher is better"},
    "triglycerides":      {"unit": "mg/dL",  "optimal": (0, 150),       "borderline": (150, 200),  "high": (200, 500),   "very_high": (500, 9999)},
    "fasting_glucose":    {"unit": "mg/dL",  "normal": (70, 100),       "prediabetes": (100, 126), "diabetes": (126, 9999)},
    "hba1c":              {"unit": "%",       "normal": (0, 5.7),        "prediabetes": (5.7, 6.5), "diabetes": (6.5, 99)},
    "hs_crp":             {"unit": "mg/L",   "low_risk": (0, 1.0),      "avg_risk": (1.0, 3.0),    "high_risk": (3.0, 9999), "note": "Cardiovascular inflammation marker"},
    "egfr":               {"unit": "mL/min/1.73m²", "normal": (90, 9999), "mild_reduce": (60, 90), "moderate_reduce": (30, 60), "severe": (0, 30), "note": "Higher is better; assess kidney function"},
    "creatinine":         {"unit": "mg/dL",  "normal_m": (0.74, 1.35),  "normal_f": (0.59, 1.04)},
    "alt":                {"unit": "U/L",    "normal_m": (7, 56),        "normal_f": (7, 45)},
    "ast":                {"unit": "U/L",    "normal": (10, 40)},
    "tsh":                {"unit": "mIU/L",  "normal": (0.4, 4.0)},
    "vitamin_d":          {"unit": "ng/mL",  "deficient": (0, 20),       "insufficient": (20, 30),  "sufficient": (30, 100)},
    "hemoglobin":         {"unit": "g/dL",   "normal_m": (13.5, 17.5),   "normal_f": (12.0, 15.5)},
    "uric_acid":          {"unit": "mg/dL",  "normal_m": (3.4, 7.0),     "normal_f": (2.4, 6.0)},
    "ferritin":           {"unit": "ng/mL",  "normal_m": (24, 336),      "normal_f": (11, 307)},
    "albumin":            {"unit": "g/dL",   "normal": (3.5, 5.0)},
}


def classify_lab(marker: str, value: float, sex: str = "male") -> dict:
    """Return status and colour for a single lab value."""
    ref = LAB_REFS.get(marker)
    if not ref:
        return {"status": "Unknown", "color": "gray"}

    def in_range(bounds, v):
        return bounds[0] <= v < bounds[1]

    if marker == "hdl_cholesterol":
        opt = ref["optimal_m"] if sex == "male" else ref["optimal_f"]
        if value >= ref["protective"][0]:
            return {"status": "Protective", "color": "green"}
        elif in_range(opt, value):
            return {"status": "Normal", "color": "green"}
        else:
            return {"status": "Low (risk)", "color": "red"}

    if marker in ("egfr",):
        if value >= ref["normal"][0]:      return {"status": "Normal",            "color": "green"}
        elif value >= ref["mild_reduce"][0]: return {"status": "Mildly reduced",   "color": "yellow"}
        elif value >= ref["moderate_reduce"][0]: return {"status": "Moderately reduced", "color": "orange"}
        else:                               return {"status": "Severely reduced",  "color": "red"}

    if marker == "fasting_glucose":
        if in_range(ref["normal"], value):      return {"status": "Normal", "color": "green"}
        elif in_range(ref["prediabetes"], value): return {"status": "Pre-diabetes range", "color": "orange"}
        else:                                     return {"status": "Diabetes range", "color": "red"}

    if marker == "hba1c":
        if value < ref["prediabetes"][0]:   return {"status": "Normal", "color": "green"}
        elif value < ref["diabetes"][0]:    return {"status": "Pre-diabetes range", "color": "orange"}
        else:                               return {"status": "Diabetes range", "color": "red"}

    if marker == "hs_crp":
        if in_range(ref["low_risk"], value):   return {"status": "Low CVD risk", "color": "green"}
        elif in_range(ref["avg_risk"], value): return {"status": "Average CVD risk", "color": "yellow"}
        else:                                  return {"status": "High CVD risk", "color": "red"}

    if marker in ("alt", "ast"):
        nrm = ref.get("normal_m") if sex == "male" else ref.get("normal_f", ref.get("normal"))
        if nrm is None: nrm = ref["normal"]
        if in_range(nrm, value): return {"status": "Normal", "color": "green"}
        else:                    return {"status": "Elevated (review)", "color": "orange"}

    if marker in ("creatinine",):
        nrm = ref["normal_m"] if sex == "male" else ref["normal_f"]
        if in_range(nrm, value): return {"status": "Normal", "color": "green"}
        else:                    return {"status": "Outside normal range", "color": "orange"}

    if marker == "hemoglobin":
        nrm = ref["normal_m"] if sex == "male" else ref["normal_f"]
        if value < nrm[0]:       return {"status": "Low (anaemia range)", "color": "red"}
        elif in_range(nrm, value): return {"status": "Normal", "color": "green"}
        else:                    return {"status": "High", "color": "orange"}

    if marker == "vitamin_d":
        if value < ref["deficient"][1]:     return {"status": "Deficient", "color": "red"}
        elif value < ref["insufficient"][1]: return {"status": "Insufficient", "color": "orange"}
        else:                               return {"status": "Sufficient", "color": "green"}

    if marker == "tsh":
        if in_range(ref["normal"], value): return {"status": "Normal", "color": "green"}
        elif value < ref["normal"][0]:     return {"status": "Low (review)", "color": "orange"}
        else:                              return {"status": "High (review)", "color": "orange"}

    # Generic: optimal then borderline
    for level, bounds in [("optimal","optimal"),("high","high"),("very_high","very_high"),("borderline","borderline")]:
        b = ref.get(level)
        if b and in_range(b, value):
            c = "green" if level == "optimal" else ("orange" if level == "borderline" else "red")
            label = {"optimal":"Optimal","borderline":"Borderline","high":"High","very_high":"Very high"}.get(level, level)
            return {"status": label, "color": c}

    return {"status": "Recorded", "color": "gray"}


# ─────────────────────────────────────────────────────────────
# Health Age Estimator (simplified lifestyle model)
# ─────────────────────────────────────────────────────────────

def estimate_health_age(
    chron_age: float,
    bmi: float,
    sbp: float,
    current_smoker: bool,
    avg_sleep: float,         # hours
    avg_steps: float,
    avg_stress: float,        # 0–10
    total_chol: Optional[float] = None,
    fasting_glucose: Optional[float] = None,
    hba1c: Optional[float] = None
) -> dict:
    """
    Lifestyle-based Health Age estimator.

    Uses well-established associations between modifiable risk factors
    and mortality/morbidity to produce an approximate 'biological age'.
    Based on methodology similar to:
      - Khaw KT et al. PLoS Med 2008 (four healthy behaviours)
      - Levine ME et al. Aging (Albany NY) 2018 (PhenoAge concept)

    This is an ESTIMATE. It is not a validated clinical tool.
    """
    age_delta = 0.0   # years older or younger than chronological age

    # BMI
    if   bmi >= 35:  age_delta += 4
    elif bmi >= 30:  age_delta += 2
    elif bmi >= 27:  age_delta += 1
    elif bmi < 18.5: age_delta += 2
    elif 18.5 <= bmi < 23: age_delta -= 1

    # Blood pressure
    if   sbp >= 160: age_delta += 5
    elif sbp >= 140: age_delta += 3
    elif sbp >= 130: age_delta += 1.5
    elif sbp < 120:  age_delta -= 1

    # Smoking
    if current_smoker: age_delta += 7

    # Sleep
    if   avg_sleep < 5:   age_delta += 4
    elif avg_sleep < 6:   age_delta += 2
    elif avg_sleep > 9.5: age_delta += 1
    elif 7 <= avg_sleep <= 8.5: age_delta -= 1

    # Physical activity (steps proxy)
    if   avg_steps >= 10000: age_delta -= 2
    elif avg_steps >= 7500:  age_delta -= 1
    elif avg_steps < 3000:   age_delta += 3
    elif avg_steps < 5000:   age_delta += 1.5

    # Stress
    if   avg_stress >= 8: age_delta += 3
    elif avg_stress >= 6: age_delta += 1

    # Labs if available
    if total_chol is not None:
        if total_chol >= 240: age_delta += 2
        elif total_chol < 160: age_delta += 1

    if hba1c is not None:
        if   hba1c >= 6.5: age_delta += 4
        elif hba1c >= 5.7: age_delta += 2
    elif fasting_glucose is not None:
        if   fasting_glucose >= 126: age_delta += 4
        elif fasting_glucose >= 100: age_delta += 1.5

    health_age = chron_age + age_delta

    if   age_delta <= -3: verdict, color = "Excellent — biologically younger", "green"
    elif age_delta <= 0:  verdict, color = "Good — on track", "green"
    elif age_delta <= 3:  verdict, color = "Moderate — small excess", "yellow"
    elif age_delta <= 6:  verdict, color = "Elevated — action recommended", "orange"
    else:                 verdict, color = "High — significant lifestyle factors", "red"

    return {
        "health_age": round(max(1, health_age), 1),
        "delta": round(age_delta, 1),
        "verdict": verdict,
        "color": color,
        "note": "Estimated only; not a clinically validated biomarker."
    }
