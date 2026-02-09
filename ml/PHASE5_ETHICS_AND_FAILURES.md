# PHASE 5: FAILURE & ETHICS ANALYSIS

## When Will the Model Fail?

### Failure Mode 1: Training-Serving Skew (Most Likely)

The model was trained on synthetic data derived from NHANES 2015–2018 
marginal distributions. Real users may differ systematically:

- **South Asian users**: lower BMI at equivalent metabolic risk; NHANES 
  is predominantly White/AA/Hispanic. The model will *underestimate* CVD 
  and diabetes risk by an estimated 1.5–2× for this group.

- **Users with BMI > 40**: training data is sparse here; predictions will 
  extrapolate rather than interpolate.

- **Young users (< 30)**: CVD events are rare; the model has few positive 
  training examples and will underestimate risk for high-risk young users 
  (e.g., familial hypercholesterolaemia).

- **Post-COVID populations**: metabolic syndrome prevalence increased 
  post-pandemic. A model trained on 2015–2018 distributions may 
  underestimate current population risk.

**Detection**: Monitor the distribution of input features in production. 
Alert when feature means drift >1 SD from training means.

---

### Failure Mode 2: Calibration Collapse Under Missing Data

When cholesterol values are missing (imputed to median), the model receives 
the same input for every such user. This creates a "median cluster" where 
predictions converge around the average, losing discriminative power for 
the users who most need it — those with abnormal lipids who haven't had 
blood tests.

**Current mitigation**: imputation flags as features; confidence score 
deducted for each imputed lab.

**Limitation**: imputation flags tell the model "this wasn't measured" 
but cannot tell it what the true value is. A user with untested LDL of 
220 mg/dL gets the same LDL input as someone with an untested LDL of 90.

---

### Failure Mode 3: The Diabetes Prevalence Problem

The synthetic generator produces ~54% diabetes prevalence in the training 
set because outcome labels are generated from a continuous logistic 
function that includes age and glucose — and the age distribution (25–80) 
produces high average glucose. This is unrealistically high.

Real-world 10-year T2D incidence in a mixed-age adult population is 
approximately 10–20% (varies by baseline risk). A model trained on 54% 
prevalence learns a very different decision boundary than one trained on 
15% prevalence.

**Impact**: The diabetes model will systematically overestimate risk for 
low-to-medium risk users. FINDRISC cross-check partially corrects for this.

**Fix required**: Replace synthetic labels with real outcome data, or 
threshold-shift the synthetic generator to match published prevalence.

---

### Failure Mode 4: User Anchoring on Numbers

Users are not Bayesian reasoners. Research consistently shows that 
displaying a numerical probability (even with uncertainty bands) causes 
users to anchor on that number and treat it as a measurement rather than 
an estimate.

A user told their CVD risk is "20–30%" will remember "about 25%" and may 
make medical decisions based on it — including *not* seeing a doctor 
("it said 25%, my dad had the same and lived fine").

The referral trigger (prominent CTA at ≥15% risk) is necessary but 
insufficient. Consider: do not display numbers at all unless confidence 
is MODERATE or above. Display risk *bands* only.

---

### Failure Mode 5: Feedback Loop (if predictions influence behaviour)

If users see their risk score and act on it (quit smoking, improve diet), 
their *measured* risk will decrease. This is good for users but creates 
a feedback loop: the model sees improving inputs and predicts improving 
outcomes, which may make a user complacent before sufficient biological 
change has actually occurred.

Smoking cessation, for example, takes 5–15 years for CVD risk to 
substantially decline. A user who quits today will see their risk score 
drop immediately (smoking_current → 0) even though their biological risk 
has not yet changed.

**Recommendation**: Display "Trajectory" (improving/stable/worsening) 
rather than absolute risk for users with < 12 months of data.

---

## Ethical Risks

### 1. Autonomy and Informed Consent

Users are providing sensitive health data (disease history, medications, 
lab results) to a system that:
- Stores it in a local SQLite database with no encryption at rest
- Processes it through a model they cannot inspect
- Returns outputs that may influence health decisions

Informed consent must be explicit: what data is collected, how long it 
is retained, how it is processed, what the model's limitations are.

**Current gap**: The disclaimer ("not a medical device") is in the footer. 
Users do not read footers. Consent should be obtained at onboarding, with 
the limitations clearly stated *before* the user enters any data.

---

### 2. Algorithmic Bias

The Pooled Cohort Equations were validated on cohorts from 1968–1993 that 
systematically excluded or underrepresented:
- South Asian, East Asian, and Middle Eastern populations
- Indigenous populations
- Transgender individuals (sex is encoded as a binary feature)
- People with rare genetic conditions (familial hypercholesterolaemia, etc.)

Our logistic regression trained on NHANES-derived synthetic data inherits 
these biases and potentially amplifies them.

**Specific harm**: Underestimating CVD risk in South Asian users creates 
false reassurance in a population with disproportionately high real-world 
CVD burden. This is not a neutral error — it is a biased error that affects 
a specific group.

**Requirement**: The population coverage warning (currently in confidence 
scoring) should be elevated to a prominently displayed limitation for every 
user who is not White or African American.

---

### 3. Privacy and Data Minimisation

The app collects, among other things: age, weight, blood pressure, glucose, 
cholesterol, family medical history, existing diagnoses, medications, 
alcohol consumption, and stress levels. This is Category A special-category 
personal data under GDPR Article 9.

Data minimisation principle: collect only what is needed for the calculation 
being performed. Currently the system collects `notes` (free text) and 
`alcohol_per_week` for features that could be asked differently.

No data is encrypted at rest. `users.db` is a plain SQLite file. If the 
machine is compromised, all user health data is immediately readable.

**Requirement**: 
- Encrypt the database (SQLCipher or similar)
- Hash/anonymise user_id in logs
- Define and enforce data retention periods
- GDPR-compliant data export and deletion endpoints

---

### 4. Risk of Medicalising Normal Variation

Health age estimators and risk scores applied to healthy, asymptomatic 
people have the potential to create unnecessary anxiety and to drive 
unnecessary medical intervention (overdiagnosis).

A 38-year-old with a BMI of 27, SBP of 128, and average stress of 6 
may be told their health age is 43. They have no symptoms. They are not 
ill. But they now believe they are "5 years older" than they should be.

This can drive anxiety, over-testing, and over-treatment. It also creates 
commercial pressure toward "optimisation" products and services.

**Recommendation**: Frame all outputs in terms of *actionable lifestyle 
changes*, not biological deficit. Do not display health age without 
explicit explanation of its limitations and the fact that it is not 
a clinical measurement.

---

## Required Safeguards (Prioritised)

| Priority | Safeguard | Current Status |
|---|---|---|
| Critical | Encrypt data at rest | ✗ Not implemented |
| Critical | Explicit informed consent at onboarding | ✗ Not implemented |
| Critical | Suppress Cancer ML model (no validated multi-cancer score exists) | ✓ Using RR indices |
| Critical | South Asian / non-PCE population warning (prominent, not footnote) | ⚠ In confidence score |
| High | Model card published alongside predictions | ✗ Not implemented |
| High | Referral CTA prominent at ≥15% CVD risk | ✓ Implemented |
| High | Confidence score gating (suppress at < 40) | ✓ Implemented |
| High | Data retention policy and deletion endpoint | ✗ Not implemented |
| Medium | Calibration monitoring (track ECE on user cohort) | ✗ Not implemented |
| Medium | Trajectory display (improving/stable/worsening) | ✗ Not implemented |
| Medium | Feature distribution monitoring (drift detection) | ✗ Not implemented |
| Low | Replace synthetic data with real outcomes | Requires data agreement |

---

# PHASE 6: NEXT STEPS

## Immediate (before any external users)

1. **Data encryption**: implement SQLCipher for `users.db`
2. **Informed consent screen**: replace footer disclaimer with explicit 
   pre-onboarding consent with checkboxes
3. **Suppress health age number**: replace "66 years" with a qualitative 
   band and explicit "estimated, not measured" framing
4. **South Asian warning promotion**: elevate from confidence score footnote 
   to banner for non-White/AA users

## Short term (1–3 months)

5. **Replace synthetic data**: apply for NHANES data access (free, requires 
   research use agreement) or use UK Biobank (institutional access required)
6. **Re-train on real data with outcome linkage**: NHANES with NDI 
   (National Death Index) linkage provides CVD mortality labels
7. **Fairness evaluation**: compute AUC stratified by race/ethnicity, 
   age band, and sex on real held-out data
8. **Calibration monitoring**: log predicted probabilities; compare to 
   observed outcomes at 6-month intervals

## Medium term (3–12 months)

9. **Regulatory assessment**: engage a regulatory consultant for SaMD 
   classification in target markets (EU MDR, FDA Software Policy)
10. **Clinical validation study**: prospective study comparing outputs to 
    clinician assessment on a small cohort
11. **Trajectory feature**: replace point-in-time estimates with 3-month 
    trend (improving/stable/worsening)
12. **Audit trail**: log all predictions with model version and input hash 
    (no PII in logs)

## Fundamental question the engineering team must answer

**Is the goal to build a medically responsible health tracking tool,
or to build a tool that looks like one?**

The current system — including after this upgrade — is a demonstration 
of correct ML engineering practice. It is not a safe medical device. 
The distance between "correct ML pipeline with SHAP" and "validated 
clinical risk tool" is measured in years of prospective studies and 
regulatory filings, not lines of code.

The most honest version of this application presents its predictions 
clearly as what they are: educational estimates, generated by a model 
trained on synthetic data, intended to motivate behaviour change — not 
to replace clinical assessment.

Any application that implies more than this to its users is making 
a promise it cannot keep.
