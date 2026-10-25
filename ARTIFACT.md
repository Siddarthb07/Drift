# Drift FAccT artifact

## What ships
- Claim-honest CVD/diabetes/cancer disclosure engine (`risk_engine.py`, `disclosure.py`, `claims.yaml`)
- Race-free PREVENT default; PCE only for White/AA
- Git-pinned legacy baseline (`legacy_baseline.py` ↔ `a8dcc33`)
- NHANES coverage + reclassification audit (`scripts/nhanes_coverage_audit.py`)
- Metamorphic honesty tests + PREVENT goldens
- Study kit (frozen PROTOCOL/OSF; server assignment; collector)
- CI: `.github/workflows/ci.yml`

## Reproduce
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export DRIFT_AUDIT=0 STUDY_ALLOW_BASELINE=1
.venv/bin/pytest -q
.venv/bin/python scripts/validate_claims.py
.venv/bin/python scripts/eval_vignettes.py
.venv/bin/python scripts/baseline_git_pin.py
.venv/bin/python scripts/check_paper_numbers.py
.venv/bin/python scripts/eval_adversarial.py
# Optional NHANES (downloads ~10MB XPTs; full eligible n=7172):
.venv/bin/python scripts/fetch_nhanes.py
.venv/bin/python scripts/nhanes_coverage_audit.py
```

## Expected
- 28+ pytest passes
- `validate_claims.py` → OK
- `eval_vignettes.py` → honest mean 1.0, mutation `all_caught`
- `eval_adversarial.py` → all_passed
- `check_paper_numbers.py` → ok
- NHANES JSON under `docs/facct/nhanes_coverage_audit.json` (n=7172)

## Non-claims
No clinical validation. Human RCT not fielded. No synthetic human results.
