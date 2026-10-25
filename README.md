# Drift

**Keywords:** claim-honest risk disclosure · AHA PREVENT (race-free) · ACC/AHA PCE · FINDRISC · FAccT artifact · wearables OAuth · Flask

**Drift** is a Flask personal health tracker that combines lifestyle logging, lab trends, wearable OAuth, and **evidence-contingent risk disclosure**. The research contribution is not a black-box predictor — it is making every on-screen health claim accountable: provenance, coverage limits, refusal instead of silent defaults, and a race-free default CVD equation usable across racial and ethnic groups.

> Educational decision-support only. **Not a medical device.** Not a diagnosis.

FAccT draft: [`docs/facct/PAPER_DRAFT.md`](docs/facct/PAPER_DRAFT.md)

## What works in this build

- Auth (SQLite + bcrypt), consent gate before onboarding, export / delete APIs
- Daily logs, 17-biomarker labs, dashboard with **honest** (default) and **baseline** (study) UI modes
- **CVD default: AHA PREVENT** (race-free, ages 30–79). Optional PCE only for White / African American when preferred
- FINDRISC with **waist intervals** when waist is missing (no silent 94/80 cm default)
- Cancer: lifestyle **factors only** in honest mode (no compounded RR hero)
- Habit trajectory replaces fictional health-age hero in honest mode
- Fitbit + Google Fit OAuth with token refresh (`oauth_watch.py`); Garmin → CSV
- Claim ledger (`claims.yaml`), calculator cards (`/model-cards`), display audit log
- Tests + disclosure audit CLI + vignette study kit (`study/`)

## Quick start

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python app_v5.py
```

Open `http://127.0.0.1:5001` → register → consent → onboarding.

```bash
pytest -q
python scripts/drift_audit.py
```

Dashboard modes: `/?mode=honest` (default) or `/?mode=baseline` (legacy study arm).

## Risk engine (honest)

Implemented in `risk_engine.py` (not the old engagement gate in `app_v5`):

| Score | Equation | Display |
|---|---|---|
| CVD | PREVENT (default); PCE optional if race ∈ {white, aa} | Risk **band** + provenance |
| Diabetes | FINDRISC | Band / score; waist missing → interval |
| Cancer | WCRF/IARC factor list | Factors only |
| Hero | Habit trajectory | Qualitative |

Missing SBP, lipids, or equation-sex → **refuse** (we do not invent 120 mmHg or median cholesterol). Age &lt; 30 → refuse CVD, not green “low risk”.

## OAuth setup

Set env vars, then register redirect URIs exactly:

`http://127.0.0.1:5001/oauth/callback/fitbit`  
`http://127.0.0.1:5001/oauth/callback/googlefit`

```bash
export FITBIT_CLIENT_ID=...
export FITBIT_CLIENT_SECRET=...
export GOOGLE_CLIENT_ID=...
export GOOGLE_CLIENT_SECRET=...
export SECRET_KEY=...   # required in production
```

Fitbit uses HTTP Basic client authentication on token exchange; Google requests offline refresh tokens. See `oauth_watch.py`.

## ML folder

`ml/` is **quarantined** — synthetic training labels, not served. See [`ml/QUARANTINE.md`](ml/QUARANTINE.md).

## FAccT / research paths

| Piece | Path |
|---|---|
| Paper draft | `docs/facct/PAPER_DRAFT.md` |
| Audit results | `docs/facct/audit_results.json` |
| Claim ledger | `claims.yaml` |
| System card | `cards/SYSTEM_CARD.md` |
| Study protocol | `study/PROTOCOL.md` |

## Safety

Not for clinical decisions. Disclaimers are in consent + UI, not only the footer.
