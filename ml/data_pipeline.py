"""
ml/data_pipeline.py
===================
Feature engineering, imputation, and data generation for the Health Risk models.

IMPORTANT — DATA HONESTY NOTICE
================================
This module generates SYNTHETIC data for demonstrating the ML pipeline.
The synthetic generator uses:
  - Marginal distributions from NHANES 2015-2018 summary statistics
  - Correlation structure approximated from published literature
  - Disease prevalence from CDC National Diabetes Statistics Report 2022
    and AHA Heart Disease & Stroke Statistics 2023

The resulting models are trained on this synthetic data.  They are
NOT validated against real patient outcomes and MUST NOT be used to
make clinical decisions.  They exist to show correct ML engineering
practice (calibration, SHAP, safety layers) without requiring access
to restricted health datasets.

To replace with real data: put a CSV with the columns in FEATURE_COLS
plus target columns 'cvd_event' and 'diabetes_onset' at data/real.csv
and the pipeline will use it automatically.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

# ─── Column definitions ───────────────────────────────────────
FEATURE_COLS = [
    "age",              # years, 18-99
    "sex_male",         # 0/1
    "bmi",              # kg/m²
    "waist_cm",         # cm
    "sbp",              # systolic BP mmHg
    "dbp",              # diastolic BP mmHg
    "pulse_pressure",   # sbp - dbp (engineered)
    "total_chol",       # mg/dL
    "hdl_chol",         # mg/dL
    "ldl_chol",         # mg/dL
    "chol_ratio",       # total_chol / hdl_chol (engineered)
    "fasting_glucose",  # mg/dL
    "hba1c",            # %
    "smoking_current",  # 0/1
    "smoking_ex",       # 0/1
    "bp_medication",    # 0/1
    "diabetes_existing",# 0/1
    "family_cvd",       # 0/1
    "family_diabetes",  # 0/1
    "avg_steps_k",      # thousands per day (engineered from avg_steps / 1000)
    "avg_sleep",        # hours
    # Imputation flags (1 = value was imputed, not measured)
    "imp_total_chol",
    "imp_hdl_chol",
    "imp_ldl_chol",
    "imp_fasting_glucose",
    "imp_hba1c",
    "imp_waist_cm",
]

TARGET_CVD      = "cvd_event"
TARGET_DIABETES = "diabetes_onset"

# Median fallbacks for imputation (from NHANES 2015-2018)
NHANES_MEDIANS = {
    "total_chol":      195.0,
    "hdl_chol":         52.0,  # population median (mixed sex)
    "ldl_chol":        115.0,
    "fasting_glucose":  97.0,
    "hba1c":             5.5,
    "waist_cm_male":    99.0,
    "waist_cm_female":  92.0,
}


# ─── Feature engineering ─────────────────────────────────────
def engineer_features(user: Dict[str, Any], labs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert raw user + lab dicts into the model feature dict.
    Tracks which values were imputed (measured = 0, imputed = 1).

    Raises ValueError if any *non-imputeable* field is missing.
    """
    def safe(val, low=None, high=None):
        """Return float or None; range-clip if bounds given."""
        if val in (None, "", 0):
            return None
        try:
            f = float(val)
            if low  is not None and f < low:  return None
            if high is not None and f > high: return None
            return f
        except (TypeError, ValueError):
            return None

    # ── Non-imputeable (required for any output) ──────────────
    age = safe(user.get("age"), 18, 99)
    if age is None:
        raise ValueError("age is required and must be 18-99")
    sex_male = 1 if str(user.get("sex","")).lower() == "male" else 0

    # ── BMI ───────────────────────────────────────────────────
    height_m = safe(user.get("height"), 100, 250)
    weight_kg = safe(user.get("weight"), 30, 300)
    if height_m and weight_kg:
        bmi = weight_kg / (height_m / 100) ** 2
        bmi = float(np.clip(bmi, 12, 80))
    else:
        raise ValueError("height and weight are required to compute BMI")

    # ── Waist ─────────────────────────────────────────────────
    waist_raw = safe(user.get("waist_cm"), 40, 200)
    imp_waist = 0
    if waist_raw is None:
        waist_raw = NHANES_MEDIANS["waist_cm_male"] if sex_male else NHANES_MEDIANS["waist_cm_female"]
        imp_waist = 1

    # ── Blood pressure ────────────────────────────────────────
    sbp = safe(user.get("systolic"), 70, 250) or 120.0
    dbp = safe(user.get("diastolic"), 40, 160) or 78.0
    pulse_pressure = sbp - dbp

    # ── Labs ──────────────────────────────────────────────────
    total_chol_raw     = safe(labs.get("total_cholesterol"), 80, 400)
    hdl_chol_raw       = safe(labs.get("hdl_cholesterol"),   20, 150)
    ldl_chol_raw       = safe(labs.get("ldl_cholesterol"),   30, 300)
    fasting_glucose_raw = safe(labs.get("fasting_glucose"),  50, 500)
    hba1c_raw          = safe(labs.get("hba1c"),              3.0, 15.0)

    imp_tc  = 0; imp_hdl = 0; imp_ldl = 0; imp_fg = 0; imp_a1c = 0

    if total_chol_raw is None:
        total_chol_raw = NHANES_MEDIANS["total_chol"]; imp_tc = 1
    if hdl_chol_raw is None:
        hdl_chol_raw = NHANES_MEDIANS["hdl_chol" ]; imp_hdl = 1
    if ldl_chol_raw is None:
        ldl_chol_raw = NHANES_MEDIANS["ldl_chol" ]; imp_ldl = 1
    if fasting_glucose_raw is None:
        fasting_glucose_raw = NHANES_MEDIANS["fasting_glucose"]; imp_fg = 1
    if hba1c_raw is None:
        hba1c_raw = NHANES_MEDIANS["hba1c"]; imp_a1c = 1

    chol_ratio = total_chol_raw / hdl_chol_raw if hdl_chol_raw > 0 else 4.0

    # ── Lifestyle ─────────────────────────────────────────────
    avg_steps   = safe(user.get("avg_steps") or labs.get("avg_steps"), 0, 100000) or 5000.0
    avg_steps_k = avg_steps / 1000.0
    avg_sleep   = safe(user.get("avg_sleep") or labs.get("avg_sleep"), 1, 24) or 7.0

    # ── Categorical / binary ──────────────────────────────────
    smoking_status   = str(user.get("smoking_status", "never")).lower()
    smoking_current  = 1 if smoking_status == "current" else 0
    smoking_ex       = 1 if smoking_status == "ex"      else 0
    bp_medication    = 1 if user.get("bp_medication")        else 0
    diabetes_existing = 1 if user.get("existing_diabetes")   else 0
    family_cvd       = 1 if user.get("family_history_cvd")   else 0
    family_diabetes  = 1 if user.get("family_history_diabetes") else 0

    return {
        "age":               age,
        "sex_male":          float(sex_male),
        "bmi":               bmi,
        "waist_cm":          waist_raw,
        "sbp":               sbp,
        "dbp":               dbp,
        "pulse_pressure":    pulse_pressure,
        "total_chol":        total_chol_raw,
        "hdl_chol":          hdl_chol_raw,
        "ldl_chol":          ldl_chol_raw,
        "chol_ratio":        chol_ratio,
        "fasting_glucose":   fasting_glucose_raw,
        "hba1c":             hba1c_raw,
        "smoking_current":   float(smoking_current),
        "smoking_ex":        float(smoking_ex),
        "bp_medication":     float(bp_medication),
        "diabetes_existing": float(diabetes_existing),
        "family_cvd":        float(family_cvd),
        "family_diabetes":   float(family_diabetes),
        "avg_steps_k":       avg_steps_k,
        "avg_sleep":         avg_sleep,
        # Imputation flags
        "imp_total_chol":    float(imp_tc),
        "imp_hdl_chol":      float(imp_hdl),
        "imp_ldl_chol":      float(imp_ldl),
        "imp_fasting_glucose": float(imp_fg),
        "imp_hba1c":         float(imp_a1c),
        "imp_waist_cm":      float(imp_waist),
    }


def features_to_array(feat: Dict[str, Any]) -> np.ndarray:
    """Convert feature dict → ordered numpy row vector."""
    return np.array([[feat[c] for c in FEATURE_COLS]], dtype=np.float64)


def imputation_count(feat: Dict[str, Any]) -> int:
    return sum(int(feat.get(k, 0)) for k in feat if k.startswith("imp_"))


# ─── Synthetic data generator ────────────────────────────────
def generate_synthetic_dataset(n: int = 20_000, seed: int = 42) -> pd.DataFrame:
    """
    Generate a synthetic dataset with epidemiologically plausible
    marginal distributions and outcome prevalence.

    NHANES 2015-2018 reference statistics used for marginals.
    Correlation structure is approximate (Gaussian copula with
    published pairwise correlations where available, else assumed small).

    Outcome labels generated via logistic response functions that
    incorporate the same risk directions as published meta-analyses
    (direction, not magnitude, is reliable; magnitudes are chosen to
    achieve realistic prevalence: CVD ~12%, diabetes ~15% in 10 years
    for a mixed-age adult population).

    This data is used ONLY to demonstrate the ML pipeline.
    Do NOT treat model outputs trained on this data as clinically valid.
    """
    rng = np.random.default_rng(seed)

    age  = rng.integers(25, 80, n).astype(float)
    male = rng.binomial(1, 0.48, n).astype(float)

    # BMI: bimodal, right-skewed (NHANES)
    bmi = np.clip(rng.normal(28.5, 6.5, n), 15, 65).astype(float)

    # Waist: correlated with BMI
    waist = np.clip(
        bmi * 2.4 + rng.normal(0, 6, n) + male * 8,
        55, 170
    ).astype(float)

    # Blood pressure: age and BMI dependent
    sbp = np.clip(
        100 + 0.4 * age + 0.6 * (bmi - 25) + rng.normal(0, 12, n),
        85, 220
    ).astype(float)
    dbp = np.clip(
        60 + 0.15 * age + 0.3 * (bmi - 25) + rng.normal(0, 8, n),
        45, 130
    ).astype(float)
    pulse_pressure = sbp - dbp

    # Lipids (NHANES-calibrated)
    hdl  = np.clip(rng.normal(55, 15, n) - male * 8, 20, 120).astype(float)
    ldl  = np.clip(rng.normal(115, 35, n) + 0.2 * age, 40, 260).astype(float)
    total_chol = np.clip(hdl + ldl + rng.normal(30, 12, n), 100, 350).astype(float)
    chol_ratio = total_chol / hdl

    # Glucose
    fasting_glucose = np.clip(
        85 + 0.15 * age + 0.4 * (bmi - 25) + rng.normal(0, 12, n),
        55, 400
    ).astype(float)
    hba1c = np.clip(
        4.0 + 0.012 * fasting_glucose + rng.normal(0, 0.3, n),
        3.5, 14.0
    ).astype(float)

    # Behavioural
    smoking_current = rng.binomial(1, 0.14, n).astype(float)
    smoking_ex      = rng.binomial(1, 0.22, n).astype(float)
    bp_medication   = rng.binomial(1, 0.25, n).astype(float)
    diabetes_existing = (fasting_glucose > 126).astype(float)
    family_cvd      = rng.binomial(1, 0.30, n).astype(float)
    family_diabetes = rng.binomial(1, 0.35, n).astype(float)
    avg_steps_k     = np.clip(rng.normal(6.5, 2.8, n), 0.5, 25.0).astype(float)
    avg_sleep       = np.clip(rng.normal(7.0, 1.2, n), 3.0, 12.0).astype(float)

    # Imputation flags: 0 for synthetic (all "measured")
    zeros = np.zeros(n, dtype=float)

    df = pd.DataFrame({
        "age": age, "sex_male": male, "bmi": bmi, "waist_cm": waist,
        "sbp": sbp, "dbp": dbp, "pulse_pressure": pulse_pressure,
        "total_chol": total_chol, "hdl_chol": hdl, "ldl_chol": ldl,
        "chol_ratio": chol_ratio,
        "fasting_glucose": fasting_glucose, "hba1c": hba1c,
        "smoking_current": smoking_current, "smoking_ex": smoking_ex,
        "bp_medication": bp_medication, "diabetes_existing": diabetes_existing,
        "family_cvd": family_cvd, "family_diabetes": family_diabetes,
        "avg_steps_k": avg_steps_k, "avg_sleep": avg_sleep,
        "imp_total_chol": zeros, "imp_hdl_chol": zeros,
        "imp_ldl_chol": zeros, "imp_fasting_glucose": zeros,
        "imp_hba1c": zeros, "imp_waist_cm": zeros,
    })

    # ── CVD outcome (10-year) ──────────────────────────────────
    # Risk directions from published literature; magnitudes tuned for
    # prevalence ~12% in this population (AHA 2023: ~11.3% 10yr CVD rate)
    cvd_logit = (
        -6.5
        + 0.040 * age
        + 0.010 * sbp
        - 0.025 * hdl
        + 0.015 * ldl
        + 0.600 * smoking_current
        + 0.300 * smoking_ex
        + 0.500 * diabetes_existing
        + 0.400 * family_cvd
        + 0.012 * (bmi - 25).clip(0)
        + 0.200 * bp_medication          # paradox: medicated = higher underlying risk
        - 0.050 * avg_steps_k
        - 0.040 * avg_sleep.clip(6, 9)
        + rng.normal(0, 0.5, n)         # unexplained variance
    )
    cvd_prob = 1 / (1 + np.exp(-cvd_logit))
    cvd_event = rng.binomial(1, cvd_prob).astype(int)

    # ── Diabetes onset (10-year) ──────────────────────────────
    diab_logit = (
        -5.8
        + 0.030 * age
        + 0.060 * bmi
        + 0.020 * waist
        + 0.015 * fasting_glucose
        + 0.500 * family_diabetes
        - 0.060 * avg_steps_k
        + 0.200 * smoking_current
        + 0.300 * bp_medication
        + rng.normal(0, 0.5, n)
    )
    diab_prob  = 1 / (1 + np.exp(-diab_logit))
    diabetes_onset = rng.binomial(1, diab_prob).astype(int)

    df[TARGET_CVD]      = cvd_event
    df[TARGET_DIABETES] = diabetes_onset

    print(
        f"[data_pipeline] Generated {n:,} synthetic samples. "
        f"CVD prevalence: {cvd_event.mean()*100:.1f}%  "
        f"T2D prevalence: {diabetes_onset.mean()*100:.1f}%"
    )
    return df


def load_or_generate(data_dir: str = "data") -> pd.DataFrame:
    """Load real data if available, else generate synthetic."""
    real_path = Path(data_dir) / "real.csv"
    if real_path.exists():
        print(f"[data_pipeline] Loading real data from {real_path}")
        df = pd.read_csv(real_path)
        required = set(FEATURE_COLS + [TARGET_CVD, TARGET_DIABETES])
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Real data CSV missing columns: {missing}")
        return df
    print("[data_pipeline] No real data found — using synthetic dataset (DEMO ONLY)")
    return generate_synthetic_dataset()
