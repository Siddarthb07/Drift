# P12 — Preregistered vignette protocol (Drift claim-honesty UI)

**Status:** Protocol draft for OSF preregistration. Do not collect participant health data in the live app for this study — use static vignette screenshots / mock dashboards only.

## Research question

Does an evidence-contingent disclosure UI (provenance badges, risk bands, coverage refusal, no health-age hero, no compounded cancer RR) reduce numeric overconfidence and false reassurance versus Drift’s legacy score-first UI, without reducing appropriate care-seeking on high-risk vignettes?

## Design

- Between-subjects, 2 arms: `baseline` vs `honest` (Drift `?mode=`).
- Optional 4-arm extension: + coverage-warning prominence; + hard refuse outside PREVENT age.
- Vignettes (fixed clinical profiles, not participants’ own data):
  1. Mid-risk White adult with complete labs (PREVENT eligible).
  2. Same vitals, South Asian ethnicity (honest → PREVENT; baseline historically → White PCE).
  3. Age 28 with labs (honest → refuse; baseline historically → green “low”).
  4. Missing waist (honest → FINDRISC interval).
  5. Missing cholesterol (refuse CVD).
  6. High-risk smoker, SBP 150, elevated lipids (referral should remain).

## Primary outcomes

1. Overconfidence: stated certainty that the estimate is a precise personal measurement (1–7) minus warranted certainty from the vignette key.
2. Comprehension: # correct of 4 items (equation coverage, health age unvalidated, cancer not a probability, FINDRISC band vs personal %).

## Secondary

- Care-seeking intent on high-risk vignette.
- Anxiety (short PANAS or single item).
- Trust / usefulness.
- Time on task.

## Sample

Target N ≈ 300 (150/arm) via Prolific; power for medium effect on primary contrast. Convenience pilots are labeled as pilots only.

## Analysis

Preregister: primary contrast honest vs baseline on overconfidence (t-test / OLS with covariates age, gender, health literacy). Multiple comparisons: Benjamini–Hochberg on secondary family.

## Ethics

IRB or exemption before recruitment. No special-category health data from participants stored in Drift `users.db`.

## Materials

- `study/vignettes.json` — profile fixtures
- `study/survey_items.md` — instruments
- Screenshots generated via `?mode=baseline|honest` on seeded personas
