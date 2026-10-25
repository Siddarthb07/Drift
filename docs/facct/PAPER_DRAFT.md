# Executable Disclosure Contracts for Consumer Health-Risk Interfaces

**Working title for ACM FAccT** (focus: *System development and deployment*; *Evaluations*)  
Artifact: Drift · Status: computational evaluation complete; human vignette study preregistered (not fielded)  
Generated tables: `docs/facct/tables.json` · `vignette_eval.json`

---

## Abstract

Consumer health apps turn published equations into screens. In that product path, harms often arise from **disclosure policy**—silent imputation, White-equation fallback for unsupported racial categories, and false-precision heroes—rather than from training a new model. We introduce **executable disclosure contracts**: a machine-readable claim ledger bound to runtime display policy (band / refuse / factors-only), enforced on the serving path.

We implement the contract in **Drift**, an open educational tracker. The default CVD path uses race-free AHA PREVENT equations so users across racial/ethnic labels receive the same calculator without invented ethnicity multipliers; optional PCE is available only for White and African American cohorts. A pinned **legacy baseline** reconstructs prior failure modes (White fallback, silent waist/SBP/cholesterol defaults, green under-40 framing, health-age and compounded cancer-RR heroes) for controlled comparison.

**Results.** Reconstructing the prior PCE White-female transcription yields **100%** 10-year risk on a standard reference profile; the corrected equation yields **2.1%**. On identical vitals, honest-mode PREVENT returns the same estimate across nine race labels (**1.9%**), while the legacy baseline maps South Asian users onto White PCE when PCE actually runs (`legacy_white_fallback=true`). Scoring both arms on the **same** six honesty keys across 16 fixtures, mean pass rates are **1.00 (honest) vs 0.56 (legacy baseline)** (Δ=+0.44; see Table 3). Missing-eGFR refusal is uniform across race strata (coverage audit). We do not claim clinical validation or substitute computational checks for human trust studies; a preregistered vignette protocol is released for follow-on work.

---

## 1. Introduction

Audits of clinical algorithms have examined race coefficients and miscalibration [1–3]. Risk-communication research shows that precision and biological-age metaphors drive anchoring and medicalization [4–6]. Between these literatures sits the **interface compiler**: code that maps equations to UI states. Footers and ethics markdown do not constrain that compiler.

**Thesis.** Accountability for consumer health-risk UIs can be operationalized as **executable disclosure contracts**—policies that make unsupported claims mechanically un-showable—evaluated against a faithful legacy baseline.

**Research questions.**
- **RQ1.** Can disclosure rules (provenance, refusal, intervals, bands) be enforced on the runtime path with testable invariants?
- **RQ2.** Can a race-free default equation provide usable CVD disclosure across racial/ethnic labels without White fallback or invented uplifts?
- **RQ3.** Relative to a reconstructed legacy UI, how large is the honesty-key pass-rate gap under identical vignette fixtures?

**Contributions.**
1. Disclosure-contract architecture (`claims.yaml` + `disclosure.py` + `risk_engine.py`).
2. Race-free PREVENT default with coverage-limited PCE; explicit equation-sex; hard refuse on missing eGFR/SBP/lipids and out-of-range BMI.
3. Pinned legacy baseline (`legacy_baseline.py`) enabling like-for-like honesty evaluation.
4. Computational results + preregistered human protocol (not fielded here).

**Non-goals.** Clinical validation; SaMD clearance; synthetic-ML AUROC as evidence; new ethnic risk coefficients.

---

## 2. Related Work

**Documentation & contracts.** Model cards and datasheets [7,8] specify intended use; FactSheets and usage cards extend documentation toward operational constraints. We push further: display policy is code on the serving path.

**Abstention / selective prediction.** Refusing to predict under distribution shift is classical [9]; we apply abstention to *consumer disclosure*, including missingness and population coverage—not only model confidence.

**Race in clinical equations.** Critiques of race correction [1] and PCE limits [2,3] motivate refusing White fallback. PREVENT’s race-free design [10] is our default deployable alternative. We do **not** treat PREVENT as globally calibrated outside its evidence base; “cross-race usability” ≠ “worldwide incidence validity.”

**Risk communication & HCI.** Numeracy, icon arrays, and uncertainty visualization [4–6,11] motivate bands over false precision and trajectory framing over biological-age heroes.

**Consumer health & regulation.** FDA SaMD / CDS guidance and EU MDR highlight labeling and intended use [12]; Drift stays educational and documents that boundary in consent UI.

---

## 3. System

### 3.1 Disclosure contract

Each output has a `claim_id` with `evidence_class`, `validated_population`, `display_policy`, and `prohibited_uses`. The engine applies policy before templates render. CI (`scripts/validate_claims.py`) fails if engine claim IDs drift from the ledger.

### 3.2 Honest routing

| Gate | Behavior |
|---|---|
| Missing SBP, lipids, eGFR, or equation-sex | Refuse CVD |
| BMI outside 18.5–39.9 or labs outside PREVENT ranges | Refuse (no clamp) |
| Age &lt;30 or &gt;79 | Refuse (not green “low”) |
| Default CVD | PREVENT (race-free) |
| Prefer PCE ∧ race∈{white,aa} ∧ age≥40 | PCE |
| Prefer PCE ∧ unsupported race | PREVENT + note |
| Missing waist (FINDRISC) | Score **interval**, not cutoff imputation |
| Cancer (honest) | Factors only if lifestyle observed; else refuse |

### 3.3 Legacy baseline (comparison arm)

`legacy_baseline.py` reconstructs prior **disclosure** behavior: unsupported race→White PCE *when PCE runs*; waist=94/80; SBP=120; under-40 green low-risk; health-age hero; compounded cancer RR. Missing cholesterol still refuses (as in the old product)—we do not invent 200/50. PCE *coefficients* use the corrected math; the 100% transcription bug is isolated in Table 1. This baseline is **not** the product default.

### 3.4 Product integrity

Consent before data entry; export/delete; OAuth with refresh + optional Fernet token sealing; homepage copy aligned with ledger; `ml/` quarantined.

---

## 4. Evaluation

### 4.1 Equation fidelity (Table 1)

White-female reference (age 55, TC 213, HDL 50, SBP 120 untreated, nonsmoker, nondiabetic):

| Implementation | Risk |
|---|---|
| Buggy transcription (reconstructed) | **100%** |
| Corrected Drift PCE | **2.1%** |

Source: Goff et al. worked-example regime; golden tests in `tests/test_pce_reference.py`.

### 4.2 Routing & fallback (Table 2)

From `tables.json`:
- Prefer-PCE: White → PCE; South Asian → PREVENT.
- South Asian identical vitals: legacy maps to White PCE (`legacy_white_fallback=true`, risk 1.8%); honest uses PREVENT band (&lt;5%, exact 1.9%).

Cross-label PREVENT parity (nine races, identical vitals) is **expected by construction** (race not an input). We report it as a wiring invariant, not a fairness discovery. The substantive fairness-relevant result is **elimination of White fallback** in the legacy comparison.

### 4.3 Shared-key vignette evaluation (Table 3)

Sixteen fixtures (6 study vignettes + 10 race×sex complete-profile grid). Both arms scored on the **same** keys. Per-key rates (`vignette_eval.json`):

| Honesty key | Honest | Legacy baseline |
|---|---|---|
| No White-PCE fallback | 1.00 | 0.50 |
| No green under-40 claim | 1.00 | 0.94 |
| No silent waist default | 1.00 | 0.94 |
| No cancer-RR hero | 1.00 | 0.00 |
| No health-age hero | 1.00 | 0.00 |
| Shows estimate when inputs complete | 1.00 | 1.00 |
| **Mean** | **1.00** | **0.56** |
| **Δ** | | **+0.44** |

The last key shows honesty does not trade away service when inputs are complete. Cancer-RR and health-age keys dominate the gap by design of the legacy arm; White-fallback remains a material intermediate gap (0.44).

### 4.4 Coverage cost of eGFR refusal (Table 4)

`scripts/coverage_audit.py` samples profiles by race × missingness. On complete inputs, honest show-rate ≈ 1.0 across races. When eGFR is missing, honest CVD refuse-rate = **1.0 for every race stratum**—a uniform coverage cost, not an ethnicity-targeted denial. We treat this as a deliberate tradeoff: inventing eGFR=90 would restore coverage by reintroducing silent defaults. Product mitigation is prompting users to enter eGFR (or a clinician-provided value), not imputation.

### 4.5 Human study

Protocol in `study/PROTOCOL.md`. **Not fielded.** RQ3’s human overconfidence endpoint remains open; computational Δ supports a systems claim about removable failure modes.

---

## 5. Discussion & limitations

Executable contracts make ethics docs falsifiable. The legacy baseline answers the “self-inflicted bug” critique by pinning failure modes as an explicit experimental control.

**Limitations.** PREVENT coefficients follow an open Supplemental-Table-S12-style reimplementation (PyPREVENT lineage); production deployments should cross-check AHA distributions. FINDRISC is European-derived. Binary equation sex excludes validated non-binary specifications. No NHANES outcome linkage here. Single-developer positionality; co-design unfinished. Without fielded humans, trust/anchoring claims stay provisional.

**Ethics.** Special-category data; consent; educational labeling; no diagnostic marketing.

---

## 6. Conclusion

Drift shows that consumer health-risk harms can be attacked at the disclosure layer: contracts, refusal, race-free defaults, and a measurable honesty gap versus a faithful legacy UI. We release the artifact for FAccT-style scrutiny and a protocol for the remaining human question.

---

## References

1. Vyas DA et al. Hidden in Plain Sight. *NEJM* 2020.  
2. Yadlowsky S et al. Revised PCE implications. *Ann Intern Med* 2018.  
3. Goff DC et al. 2013 ACC/AHA risk guideline. *Circulation* 2014.  
4. Gigerenzer G et al. Helping doctors and patients make sense of health statistics. *Psychol Sci Public Interest* 2007.  
5. Fagerlin A et al. Patient decision aids / risk communication reviews.  
6. Ancker JS et al. Design features of graphs in health risk communication.  
7. Mitchell M et al. Model Cards. *FAccT* 2019.  
8. Gebru T et al. Datasheets for Datasets. *CACM* 2021.  
9. Chow C. On optimum recognition error and reject tradeoff. *IEEE Trans IT* 1970.  
10. Khan SS et al. AHA PREVENT equations. *Circulation* 2024.  
11. Hullman J, Kay M et al. Uncertainty visualization / graphical inference.  
12. FDA. Clinical Decision Support / SaMD guidance documents.  
13. Lindström J, Tuomilehto J. FINDRISC. *Diabetes Care* 2003.

---

## Appendix — Reproduce

```bash
pip install -r requirements.txt
pytest -q
python scripts/validate_claims.py
python scripts/drift_audit.py
python scripts/eval_vignettes.py
# regenerates docs/facct/vignette_eval.json; tables via interpreter snippet in CI notes
python app_v5.py  # ?mode=honest|baseline
```

Artifact paths: `legacy_baseline.py`, `risk_engine.py`, `claims.yaml`, `study/`, `cards/SYSTEM_CARD.md`, `ml/QUARANTINE.md`.
