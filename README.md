# Drift

**Keywords:** clinical risk scoring · ACC/AHA · FINDRISC · biomarkers · health tracker · wearables OAuth · Flask · explainable ML

**Drift** (repo formerly branded Health-AI) is a Flask-based personal health tracking platform that combines daily lifestyle logging, 17-biomarker lab trend tracking, smartwatch OAuth ingestion, and evidence-based clinical risk estimation (ACC/AHA Pooled Cohort + FINDRISC).

## What This Repo Actually Does

- User auth with local SQLite + bcrypt password hashing
- Guided onboarding for demographics, vitals, and history
- Daily logs for sleep, steps, stress, hydration, food quality, and notes
- Lab entry and historical lab timeline for 17 biomarkers
- Risk scoring with hard gating rules before any risk is shown
- OAuth smartwatch sync (Fitbit and Google Fit implemented)
- CSV import path for Apple Health style exports
- JSON API endpoints for daily history and risk summary

The app runs from `app_v5.py` and defaults to port `5001`.

## Risk Engine In This Version

The current runtime risk pipeline is rule-based and transparent, not a black-box classifier:

- CVD: ACC/AHA Pooled Cohort Equations
- Diabetes: FINDRISC score
- Cancer: lifestyle relative-risk model (not absolute incidence probability)
- Health Age: heuristic estimator based on lifestyle and labs

Implementation is in `risk_calculators.py` and called through `compute_risk_scores()` in `app_v5.py`.

### Gating Rules Before Risk Is Displayed

`compute_risk_scores()` enforces:

1. Profile must include age, sex, height, weight
2. At least 7 daily logs must exist
3. At least one lab panel entry must exist
4. CVD additionally requires total cholesterol and HDL, and age 40+

If these conditions are not met, the UI returns explicit gated messages instead of fake numbers.

## Data Model

SQLite DB: `users.db`

Tables created at startup:

- `users`
- `daily_log`
- `lab_results`
- `surveys`

Notable tracked fields include BP medication status, smoking status, alcohol/week, race, family history flags, wearable provider/token, and health goals.

## Smartwatch and Import Flows

### OAuth Providers Configured

`OAUTH_CFG` supports config keys for:

- `fitbit`
- `googlefit`
- `garmin` (configured in env map, but sync logic currently handles Fitbit and Google Fit)

### Sync Endpoint

- `GET /api/sync_watch`

Behavior:

- Pulls current-day steps/active/sleep via provider APIs
- Upserts into `daily_log` with `source='watch'`

### CSV Import Endpoint

- `POST /import_csv`

Expected columns include:

- `date`
- `sleep`
- `steps`
- `active_minutes`

Imported rows are upserted into `daily_log` with `source='csv_import'`.

## ML Folder Note (`ml/`)

This repo also contains an advanced experimental ML stack under `ml/` (`predictor.py`, `train_model.py`, `safety.py`, etc.).

Design notes and phase plan: [`ml/AUDIT_AND_DESIGN.md`](ml/AUDIT_AND_DESIGN.md).

Important: the primary runtime in `app_v5.py` currently uses the rule-based calculator path from `risk_calculators.py`, not the `ml/` predictor as the default serving path.

## Local Setup

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
# source venv/bin/activate

pip install -r requirements.txt
python app_v5.py
```

Open: `http://127.0.0.1:5001`

## Optional Environment Variables

- `SECRET_KEY`
- `FITBIT_CLIENT_ID`
- `FITBIT_CLIENT_SECRET`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GARMIN_CLIENT_ID`
- `GARMIN_CLIENT_SECRET`

## Core Routes

- `/` home
- `/register`, `/login`, `/logout`
- `/onboarding/<step>`
- `/dashboard`
- `/labs`
- `/profile`
- `/smartwatch`
- `/connect/<provider>` and `/oauth/callback/<provider>`
- `/survey`
- `/api/daily_history`
- `/api/risk_summary`

## Safety and Scope

This project is educational and decision-support only. It is not a medical device and is not a diagnostic substitute for clinician review.

