# Health AI Tracker — Critical ML Engineering Audit
## Senior ML Engineer Review | All Phases

---

# PHASE 1: CRITICAL ANALYSIS

## 1. Why This Is NOT a True AI System

### The core problem: rule encoding masquerading as AI

The current system (`risk_calculators.py`) implements **deterministic clinical
calculators** — valid tools, but not machine learning. Every "prediction" is a
closed-form mathematical function with no learned parameters, no training data,
and no ability to improve or generalise from observations.

Specific failures:

**A. No model has been trained.**
`pooled_cohort_cvd_10yr` is a transcription of the PCE regression coefficients
published in Goff et al. 2014. Those coefficients were learned from 25,000 patient
records — but *we* learned nothing. We merely copied finished work.

**B. The health age estimator is completely made up.**
`estimate_health_age` contains deltas like `age_delta += 7` for current smoking
and `age_delta -= 1` for 18.5 ≤ BMI < 23. These numbers have no data source.
The docstring cites Levine et al. 2018 (PhenoAge), but PhenoAge uses nine serum
biomarkers fitted via penalised Cox regression. Our version uses if/elif trees.
This is not an adaptation of that methodology — it is a fiction that borrows
the name.

**C. The cancer "relative risk" model is an additive RR toy.**
`cancer_lifestyle_risk` multiplies RR factors from different studies measuring
different cancer types, in different populations, over different time horizons.
Multiplying them together assumes independence and additivity — a known invalid
assumption in epidemiology. The WCRF does not endorse a combined multi-cancer RR
score. We invented one.

**D. FINDRISC is correctly transcribed but produces systematic errors without
waist circumference.** When `waist_cm` is null we default to the risk threshold
itself (94 cm for males), which silently sets the waist score to the *borderline*
band for every user who hasn't measured their waist. This is a data imputation
bug that biases scores upward.

**E. No model calibration.**
We output `risk_pct` values to one decimal place implying precision we do not
have. The PCE was calibrated on cohorts from 1968–1993. It is known to
*overestimate* risk in contemporary, treated populations by 1.5–2×
(Yadlowsky et al., Annals of Internal Medicine, 2018). We make no adjustment.

**F. No uncertainty quantification.**
Every output is a point estimate. A 45-year-old male with borderline inputs
might have a true CVD risk anywhere between 4% and 9%, yet we display a single
number ("2.5%") as if it were a measurement, not an estimate.

**G. No evaluation has been performed on this deployment.**
We cannot answer: what is the sensitivity of this system? What fraction of
high-risk users does it correctly identify? What is the false positive rate?
These questions have no answer because we never tested the system against
outcomes.

---

## 2. Risks of Deploying This System

### Clinical risks

**Under-detection of high-risk individuals.** The PCE is calibrated for
White and African American populations from specific US cohorts. South Asian
users — a population with substantially elevated CVD and T2D risk at lower BMI
thresholds — will be systematically *underscored*. A 42-year-old South Asian
male with a BMI of 24 and SBP of 130 may be told "Low (<5%)" when their actual
risk, adjusted for South Asian-specific metabolic physiology, is 2–3× higher.

**False reassurance from incomplete data.** If a user hasn't entered cholesterol
values, CVD shows "—" with a note. Nothing prevents them from interpreting their
Diabetes score of "Low" as an overall green light.

**The health age number is the most dangerous output.** It has no clinical
validation, no published methodology, and yet it is displayed prominently at
the top of the dashboard as a large, coloured number. Users will anchor on it.

### Regulatory risks

In most jurisdictions, software that makes health risk predictions for
individual users meets the definition of a **Software as a Medical Device
(SaMD)**. In the EU, this triggers MDR compliance (Class IIa minimum). In the
US, the FDA has regulatory authority over clinical decision support software.
Displaying individual probability estimates for cancer, CVD and diabetes without
clinical validation is likely a regulatory violation.

### Reputational and liability risks

A user who receives a "Low" CVD score and subsequently has a myocardial
infarction has reasonable grounds to argue the tool provided false assurance.
The disclaimer ("not a medical device") is not a legal shield when the system
is *designed* to produce clinical predictions.

---

## 3. Missing Components Required for Credibility

| Component | Current Status | Required |
|---|---|---|
| Training dataset | None | N-of-thousands, labelled with outcomes |
| Trained model | None (rule functions) | Calibrated probabilistic classifier |
| Cross-validation | None | Stratified k-fold, temporal hold-out |
| Calibration | None | Platt scaling or isotonic regression |
| ROC-AUC / Brier score | None | Reported per model, per demographic |
| Uncertainty bounds | None | Confidence intervals on every estimate |
| SHAP / feature attribution | None | Per-prediction explanation |
| Subgroup fairness metrics | None | Stratified AUC by sex, age, ethnicity |
| Clinical validation | None | Comparison to reference standard |
| Safety layer | Disclaimer text only | Confidence thresholding, edge-case detection |
| Audit trail | None | Logged inputs, outputs, model version |
| Model versioning | None | MLflow or equivalent |
| Regressor drift detection | None | Distribution monitoring |

---

# PHASE 2: SYSTEM REDESIGN

## Target Architecture: Explainable Health Risk Prediction System

```
┌─────────────────────────────────────────────────────────────────────┐
│                        USER INTERFACE (Flask)                       │
│   Dashboard · Labs · Profile · Smartwatch · Onboarding             │
└────────────────────────────┬────────────────────────────────────────┘
                             │ user inputs
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       INPUT VALIDATION LAYER                        │
│  · Schema validation (Pydantic / marshmallow)                       │
│  · Range checks (age 18-99, SBP 70-250, …)                         │
│  · Completeness scoring (which features are present?)               │
│  · Imputation flags (which values were imputed vs measured?)        │
└────────────────────────────┬────────────────────────────────────────┘
                             │ validated, flagged feature vector
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         DATA PIPELINE                               │
│                                                                     │
│  ┌─────────────────────┐    ┌────────────────────────────────────┐  │
│  │  Feature Engineering│    │        Imputation Engine           │  │
│  │  · BMI from H/W     │    │  · Median imputation (num)         │  │
│  │  · pulse pressure   │    │  · Most-frequent (cat)             │  │
│  │  · log transforms   │    │  · Imputation flags as features    │  │
│  │  · interaction terms│    │  · NO silent imputation            │  │
│  └─────────────────────┘    └────────────────────────────────────┘  │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │              StandardScaler (fitted on training set)            │ │
│  └─────────────────────────────────────────────────────────────────┘ │
└────────────────────────────┬────────────────────────────────────────┘
                             │ scaled feature matrix
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          MODEL LAYER                                │
│                                                                     │
│  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐   │
│  │  CVD Model       │ │  Diabetes Model  │ │  (Cancer: RR     │   │
│  │  Logistic Reg.   │ │  Logistic Reg.   │ │   indices only,  │   │
│  │  + calibration   │ │  + calibration   │ │   no ML model)   │   │
│  │  AUC ~0.72       │ │  AUC ~0.78       │ │                  │   │
│  └────────┬─────────┘ └────────┬─────────┘ └──────────────────┘   │
│           │                    │                                     │
│  ┌────────▼────────────────────▼──────────────────────────────────┐ │
│  │            Model Registry (joblib bundle)                       │ │
│  │  { model, scaler, features, version, training_date, metrics }  │ │
│  └────────────────────────────────────────────────────────────────┘ │
└────────────────────────────┬────────────────────────────────────────┘
                             │ raw probability
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      EXPLAINABILITY LAYER                           │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │  SHAP Linear Explainer (fast, exact for linear models)          ││
│  │  · per-feature SHAP values for this prediction                  ││
│  │  · top-3 risk-raising factors                                   ││
│  │  · top-3 risk-lowering (protective) factors                     ││
│  │  · human-readable natural language mapping                      ││
│  └─────────────────────────────────────────────────────────────────┘│
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │  Counterfactual Generator                                       ││
│  │  "If you reduced smoking: risk drops from 18% → 11%"           ││
│  └─────────────────────────────────────────────────────────────────┘│
└────────────────────────────┬────────────────────────────────────────┘
                             │ probability + explanation
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         SAFETY LAYER                                │
│                                                                     │
│  ┌──────────────────────┐   ┌─────────────────────────────────────┐ │
│  │  Confidence Scorer   │   │  Edge Case Detector                 │ │
│  │  · input completeness│   │  · out-of-distribution inputs       │ │
│  │  · imputation count  │   │  · extreme values flagged           │ │
│  │  · population match  │   │  · South Asian / non-PCE pop. warn  │ │
│  └──────────────────────┘   └─────────────────────────────────────┘ │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │  Output Formatter                                               ││
│  │  · risk band (not false-precision point estimate)               ││
│  │  · confidence level (HIGH / MODERATE / LOW)                     ││
│  │  · mandatory disclaimer injection                               ││
│  │  · referral trigger (if HIGH risk → "See a doctor" prominent)   ││
│  └─────────────────────────────────────────────────────────────────┘│
└────────────────────────────┬────────────────────────────────────────┘
                             │ safe, explained output bundle
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          AUDIT LOG                                  │
│  · timestamp, user_id_hash, model_version                           │
│  · input feature hash (no PII stored in log)                        │
│  · output risk band, confidence, SHAP top features                  │
│  · SQLite table: prediction_log                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Module Responsibilities

| Module | File | Responsibility |
|---|---|---|
| Data pipeline | `ml/data_pipeline.py` | Feature engineering, scaling, imputation flags |
| Training | `ml/train_model.py` | Train, calibrate, evaluate, serialise models |
| Predictor | `ml/predictor.py` | Load model, run SHAP, return explanation bundle |
| Safety layer | `ml/safety.py` | Confidence scoring, edge detection, output formatting |
| Integration | `ml/integrate.py` | Drop-in replacement for `compute_risk_scores()` |

---

# PHASE 3: IMPLEMENTATION PLAN

## Step 1: Dataset Structure

**Why synthetic data with epidemiological constraints is used here:**
Real patient outcome data (NHANES with mortality linkage, UK Biobank) requires
data access agreements. The synthetic data generator below uses published
prevalence statistics to produce realistic marginal distributions and
known correlations. It is *honest about what it is* and is only used to
demonstrate the pipeline — not to make clinical claims.

**Features (19 inputs → model):**
age, sex_male, bmi, waist_cm, sbp, dbp, total_chol, hdl_chol, ldl_chol,
fasting_glucose, hba1c, smoking_current, smoking_ex, bp_medication,
diabetes_existing, family_cvd, family_diabetes, avg_steps, avg_sleep

**Targets (binary, separate models):**
- `cvd_event`: 1 = MI or stroke within 10 years
- `diabetes_onset`: 1 = T2D diagnosis within 10 years

**Inputs / Outputs:**
- Input: raw user dict from DB
- Output: scaled numpy array + imputation flag dict

## Step 2: Model Training

**Algorithm: Logistic Regression with L2 regularisation**

Rationale for *not* using tree ensembles or neural networks:
1. Linear models are exactly compatible with SHAP Linear Explainer (O(n), not O(n·2^d))
2. Coefficients are directly interpretable
3. Gradient boosting gives marginally better AUC (~0.02) at the cost of
   explainability and calibration complexity
4. Sample sizes in this domain don't justify deep models

**Training protocol:**
- Stratified 5-fold cross-validation
- Calibration: Platt scaling (sigmoid) via CalibratedClassifierCV
- Hyperparameter: C tuned via cross_val_score on Brier score (not AUC — Brier
  penalises overconfident wrong predictions)

**Expected metrics (synthetic data, for demonstration):**
- CVD: ROC-AUC ~0.72, Brier ~0.18
- Diabetes: ROC-AUC ~0.78, Brier ~0.15

## Step 3: Evaluation Metrics

| Metric | What it measures | Threshold |
|---|---|---|
| ROC-AUC | Discrimination (can model rank risk?) | > 0.70 |
| Brier score | Calibration (are probabilities accurate?) | < 0.25 |
| Sensitivity at 80% specificity | Clinical operating point | > 0.60 |
| ECE (Expected Calibration Error) | Reliability diagram deviation | < 0.05 |
| AUC by subgroup (sex, age band) | Fairness | Max gap < 0.08 |

## Step 4: Explainability (SHAP)

**Method: SHAP Linear Explainer**

For logistic regression: `SHAP value = coefficient × (feature − mean)`
This is exact (no approximation), fast (< 1ms per prediction), and maps
directly back to feature names.

Output per prediction:
```json
{
  "shap_values": {"sbp": 0.043, "smoking_current": 0.21, "hdl_chol": -0.031, ...},
  "top_risk_factors":     [{"feature": "smoking_current", "shap": 0.21, "label": "Current smoker"}],
  "top_protective":       [{"feature": "hdl_chol", "shap": -0.031, "label": "HDL cholesterol"}],
  "counterfactuals":      [{"change": "Quit smoking", "new_risk_pct": 9.1, "delta": -5.3}]
}
```

## Step 5: Safety Layer

**Confidence scoring (0–100):**
- Start at 100
- -15 per imputed feature (missing = uncertainty)
- -20 if age outside training distribution (< 30 or > 79)
- -10 if BMI outside training distribution (< 15 or > 55)
- -15 if population is South Asian (PCE not validated)
- Floor at 0

**Confidence → display label:**
- 70–100: MODERATE (no model reaches HIGH without clinical validation)
- 40–69:  LOW — "Estimate based on incomplete data"
- < 40:   VERY LOW — suppress numeric output, show only qualitative band

**Risk bands (replace point estimates):**
Instead of "14.2%", display "10–20% estimated 10-year risk"
Bands: <5%, 5–10%, 10–20%, 20–30%, >30%

**Referral trigger:**
If risk_band ≥ 20% OR confidence ≤ 40 with any elevated factor:
inject prominent "Discuss this result with a doctor" CTA, not just footer text.
