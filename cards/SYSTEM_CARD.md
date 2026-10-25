# Drift system card

**Intended use:** Educational personal health logging with claim-honest disclosure of published risk equations (default: race-free AHA PREVENT for CVD; FINDRISC for diabetes; lifestyle factor lists for cancer-related habits).

**Out of scope:** Diagnosis, treatment, insurance underwriting, emergency triage, or clinical trial primary endpoints.

**Default CVD equation:** PREVENT (Khan et al. 2024) — race-free, sex-specific, ages 30–79. Race/ethnicity is collected for transparency and optional US PCE comparison only when race ∈ {white, aa}.

**Prohibited runtime behaviors (enforced in `risk_engine.py`):**
- Silent mapping of non-White/non-AA users onto White PCE coefficients
- Silent waist = 94/80 cm FINDRISC imputation
- Silent SBP = 120
- Green “under 40 = low risk” framing
- Health-age hero number in honest mode
- Compounded multi-cancer RR gauge in honest mode

**Experimental ML (`ml/`):** Not served. Synthetic labels; quarantined as a negative exhibit.

**Logging:** Display decisions appended to `audit_display.jsonl` with user hash + input hash (no raw labs).

**Consent:** `/consent` before onboarding; export `/api/export`; delete `/api/delete_account`.
