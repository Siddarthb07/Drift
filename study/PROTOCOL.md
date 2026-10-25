# Preregistered vignette protocol (Drift claim-honesty UI)

**Status:** Frozen for OSF timestamp. Do not recruit until IRB/exemption letter is on file.  
**Aligned with:** `osf/preregistration.json`, `prolific_survey.html`, `scripts/analyze_study.py`

## Research question

Does an evidence-contingent disclosure UI (bands, coverage refusal, no health-age hero, no compounded cancer RR, no White-PCE fallback) reduce calibrated overconfidence versus Drift’s legacy score-first UI, without reducing care-seeking intent on a high-risk vignette?

## Design

- Between-subjects, 2 arms: `honest` vs `baseline` (server-assigned; SQLite; not in cookie).
- Four vignettes (engine-rendered): mid-risk White; same vitals South Asian; age 28 refuse vs green; high-risk smoker.
- Vignette order shuffled per participant.
- **Not** a factorial ablation in v1 (bundled treatment acknowledged as limitation).

## Primary outcome (single)

**Calibrated overconfidence:** mean over vignettes of (stated precision certainty 1–7 − warranted certainty key for that vignette×arm display).  
Warranted keys dual-coded by clinicians and locked in `study/warranted_certainty.json` before data collection.

## Secondary outcomes

1. Comprehension: proportion correct on race-handling item (v2 only) + health-age item (asked once at end).
2. Care-seeking intent on high-risk vignette (v6): Likert 1–7; TOST non-inferiority margin 0.5 (exploratory power).
3. Attention-check pass.

## Sample

- Pilot N=40 labeled pilot.
- Confirmatory N≈600 analyzed (300/arm); power d=0.25 two-sided α=.05 → ~252/arm + attrition.
- Quotas: ≥30% Black, Hispanic, or Asian combined (exploratory arm×race).

## Analysis

LMM / OLS with cluster-robust SE at participant level: calibrated overconfidence ~ arm (+ covariates age, gender, health literacy if collected). BH-FDR on secondary family. Confirmatory vs exploratory sections separated. `scripts/analyze_study.py`.

## Ethics

IRB/exemption before recruitment. Fictional vignettes only. Study DB separate from product `users.db`. No IP storage. Prolific ID for payment only.

## Materials

`vignettes.json`, `rendered_fixtures.json`, `prolific_survey.html`, `survey_items.md`, `warranted_certainty.json`, `IRB_EXEMPTION_REQUEST.md`
