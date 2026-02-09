# HealthTracker v5

A privacy-first, evidence-based personal health tracking application.

---

## What's New in v5 vs v4

| Area | v4 | v5 |
|---|---|---|
| Risk predictions | Synthetic ML model (fake/hallucinated) | Validated clinical algorithms |
| CVD | Synthetic GBM | ACC/AHA Pooled Cohort Equations |
| Diabetes | Synthetic GBM | FINDRISC Score |
| Cancer | Synthetic GBM | WCRF/AICR Relative Risk |
| Health Age | Not present | PhenoAge-inspired estimator |
| Watch sync | Random number generator | Real Fitbit / Google Fit API calls |
| Apple Health | Not supported | CSV import |
| Lab markers | Not present | 17 biomarkers with reference ranges |
| Lab trends | Not present | Timeline charts for all markers |
| Profile fields | 7 fields | 20+ fields (waist, race, smoking, alcohol…) |

---

## Setup

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run
python app_v5.py
# Open http://localhost:5001
```

---

## Smartwatch Integration

### Fitbit (Recommended)

1. Go to https://dev.fitbit.com/apps/new
2. Set application type: **Personal**
3. Set callback URL: `http://localhost:5001/oauth/callback/fitbit`
4. Copy Client ID and Client Secret

```bash
export FITBIT_CLIENT_ID="your_client_id"
export FITBIT_CLIENT_SECRET="your_client_secret"
python app_v5.py
```

### Google Fit

1. Go to https://console.cloud.google.com/ → Create project
2. Enable **Fitness API**
3. OAuth consent screen → External → add yourself as test user
4. Credentials → OAuth 2.0 Client → Web application
5. Add redirect URI: `http://localhost:5001/oauth/callback/googlefit`

```bash
export GOOGLE_CLIENT_ID="your_client_id.apps.googleusercontent.com"
export GOOGLE_CLIENT_SECRET="your_secret"
```

### Apple Health (CSV Import)

On your iPhone:
1. Open **Health** app → tap your profile photo (top right)
2. **Export All Health Data** → saves as a .zip
3. Unzip → `export.xml`
4. Convert to CSV using: https://www.ericwolter.com/projects/apple-health-export/
   - Required columns: `date`, `steps`, `sleep`
   - Optional: `active_minutes`, `water_ml`
5. Import via the **Watch & Device Sync** page in the app

---

## Risk Score Methodology

### CVD — ACC/AHA Pooled Cohort Equations

- **Source:** Goff DC Jr et al. *Circulation.* 2014;129(25 Suppl 2):S49-73. DOI:10.1161/01.cir.0000437741.48606.98
- **What it calculates:** 10-year risk of first atherosclerotic cardiovascular event (heart attack or stroke)
- **Required inputs:** Age (40–79), sex, race, total cholesterol, HDL cholesterol, systolic BP, BP medication status, smoking, diabetes
- **Validated on:** ARIC, CARDIA, CHS, Framingham Original and Offspring cohorts — ~25,000 participants
- **Note:** Enter lab cholesterol values to unlock this calculation. Without cholesterol values, the calculator cannot run.

### Diabetes — FINDRISC

- **Source:** Lindström J, Tuomilehto J. *Diabetes Care.* 2003;26(3):725-731. DOI:10.2337/diacare.26.3.725
- **What it calculates:** 10-year risk of developing Type 2 diabetes
- **Required inputs:** Age, BMI, waist circumference, physical activity, fruit/vegetable intake, BP medication, blood glucose history, family history
- **Validated on:** 4,746 Finnish adults, followed 10 years; sensitivity 78%, specificity 77%
- **Score interpretation:**
  - < 7: ~1% 10-year risk (Low)
  - 7–11: ~4% (Slightly elevated)
  - 12–14: ~17% (Moderate)
  - 15–20: ~33% (High)
  - > 20: ~50% (Very high)

### Cancer — Lifestyle Risk Indicator

- **Sources:**
  - WCRF/AICR Third Expert Report. *Diet, Nutrition, Physical Activity and Cancer: a Global Perspective.* 2018. Available: https://www.wcrf.org/dietandcancer
  - IARC Monographs on the Evaluation of Carcinogenic Risks to Humans (tobacco, alcohol, obesity)
  - Renehan AG et al. *Lancet.* 2008;371(9612):569-578 (obesity & cancer)
- **Important:** This returns a **relative risk multiplier vs. average lifestyle**, NOT an absolute probability. Cancer is highly heterogeneous; no single validated score covers all cancer types. This is an educational tool only.

### Health Age Estimator

- **Inspired by:** Levine ME et al. *Aging (Albany NY).* 2018;10(4):573-591; Khaw KT et al. *PLoS Med.* 2008;5(1):e12
- **Method:** Lifestyle and biomarker adjustments to chronological age based on published associations with all-cause mortality
- **Important:** This is an estimate only, not a validated clinical tool. It is intended to motivate lifestyle change, not provide a medical assessment.

---

## Lab Reference Ranges

All reference ranges sourced from:
- ARUP Laboratories Reference Intervals: https://www.aruplab.com/testing/resources/intervals
- Mayo Clinic Laboratories Test Catalog
- ACC/AHA, ADA, AASLD, ASN clinical guidelines where applicable

---

## Disclaimer

HealthTracker is an informational tool only. All risk scores are population-level estimates and **are not a clinical diagnosis or substitute for consultation with a qualified healthcare provider**. Always discuss your health concerns and test results with your doctor.

This application does not store or transmit data to any external server. All data is stored locally in `users.db`.

---

## Privacy

- Passwords hashed with bcrypt (cost factor 12)
- No external analytics, no ads, no data sharing
- OAuth tokens stored locally, never transmitted
- All computation runs locally
