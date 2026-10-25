# Executable Disclosure Contracts for Consumer Health-Risk Interfaces

**Working title for ACM FAccT** (tracks: *System development and deployment*; *Evaluations*)  
Artifact: **Drift** · Status: computational + NHANES coverage evaluation complete; human vignette RCT **preregistered and instrument-hardened, not yet fielded** (IRB determination pending)  
Reproduce: `docs/facct/*.json` · `study/` · `scripts/`

---

## Abstract

Consumer health apps turn published equations into screens. In that product path, harms often arise from **disclosure policy**—silent imputation, White-equation fallback for unsupported racial categories, and false-precision heroes—rather than from training a new model. We introduce **executable disclosure contracts**: a machine-readable claim ledger bound to runtime display policy (band / refuse / factors-only), enforced on the serving path.

We implement the contract in **Drift**, an open educational tracker. The default CVD path uses race-free AHA PREVENT equations; optional PCE is available only for White and African American cohorts. A pinned **legacy baseline** (git `a8dcc33`) reconstructs prior failure modes for controlled comparison.

**Results.** (1) Correcting a PCE White-female transcription bug changes a reference profile from **100%** to **2.1%** 10-year risk. (2) PREVENT coefficients match published worked examples (female high-risk ASCVD **9.2%** within 0.35pp). (3) On NHANES 2017–March 2020 adults (n=2500), **by construction** every legacy PCE score for non-White/non-AA races is a White fallback; NHANES estimates the **burden**: **228 Asian** and **405 Hispanic** profiles in-sample receive a misattributed equation under legacy (0 White/AA). Honest-mode show rates are ~55–65% across strata; refusal tracks missing labs/BMI—not ethnicity remapping. (4) Shared-key fixtures: honest vs legacy **1.00 vs 0.61** (core Δ=+0.14 after excluding always-on heroes); mutation tests catch injected failures. A documentation audit of professional calculators vs consumer “health age” class situates the legacy arm externally. We do **not** claim clinical validation or fielded human trust results; a preregistered N≈600 RCT (server-side concealed assignment, engine-rendered cards) awaits IRB.

---

## 1. Introduction

Audits of clinical algorithms have examined race coefficients and miscalibration [1–3]. Risk-communication research shows that precision and biological-age metaphors drive anchoring and medicalization [4–6]. Between these literatures sits the **interface compiler**: code that maps equations to UI states. Footers and ethics markdown do not constrain that compiler.

**Thesis.** Accountability for consumer health-risk UIs can be operationalized as **executable disclosure contracts**—policies that make unsupported claims mechanically un-showable—evaluated against a faithful legacy baseline and population coverage data.

**Research questions.**
- **RQ1.** Can disclosure rules (provenance, refusal, intervals, bands) be enforced on the runtime path with testable invariants (including mutation tests)?
- **RQ2.** Does a race-free default eliminate White-equation fallback on real demographic strata (NHANES), and what coverage cost does honest refusal impose by group?
- **RQ3.** Relative to a reconstructed legacy UI, how large is the honesty-key pass-rate gap under identical fixtures? *(Human overconfidence remains preregistered, not fielded.)*

**Contributions.**
1. Disclosure-contract architecture (`claims.yaml` + `disclosure.py` + `risk_engine.py`) with CI validation and mutation-tested honesty keys.
2. Race-free PREVENT default with coverage-limited PCE; golden tests against published PREVENT worked examples.
3. Pinned legacy baseline (`legacy_baseline.py`, behaviors present at `a8dcc33`).
4. NHANES disclosure-disparity audit (fallback and show/refuse by race).
5. Field-ready human protocol (OSF draft prereg, IRB exemption packet, Prolific survey without arm/annotation leakage, `/study/collect`).

**Non-goals.** Clinical validation; SaMD clearance; synthetic-ML AUROC as evidence; new ethnic risk coefficients; claiming RQ3 human endpoints without fielded data.

---

## 2. Related Work

**Documentation & contracts.** Model cards and datasheets [7,8] specify intended use; FactSheets and usage cards extend documentation toward operational constraints [14]. We push further: display policy is code on the serving path.

**Abstention / selective prediction.** Refusing to predict under distribution shift is classical [9]; we apply abstention to *consumer disclosure*, including missingness and population coverage—not only model confidence.

**Race in clinical equations.** Critiques of race correction [1] and PCE limits [2,3] motivate refusing White fallback. PREVENT’s race-free design [10] is our default deployable alternative. Race-free is not synonymous with globally calibrated incidence; eGFR race debates [15] illustrate adjacent stakes. We do **not** treat PREVENT as worldwide-valid.

**Risk communication & HCI.** Numeracy, icon arrays, and uncertainty visualization [4–6,11] motivate bands over false precision and trajectory framing over biological-age heroes.

**Consumer health & regulation.** FDA SaMD / CDS guidance and EU MDR highlight labeling and intended use [12]; Drift stays educational and documents that boundary in consent UI.

**Algorithmic audits & healthcare ML.** Obermeyer et al. [16] and Raji et al. [17] motivate empirical audits of deployed systems; Chen et al. [18] survey fairness in healthcare ML. We audit the *disclosure compiler*, not a learned predictor.

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

`legacy_baseline.py` reconstructs disclosure behavior verified present in git `a8dcc33` (`docs/facct/baseline_git_pin.json`): unsupported race→White PCE *when PCE runs*; waist=94/80; SBP=120; under-40 green low-risk; health-age hero; compounded cancer RR. Missing cholesterol still refuses. PCE *coefficients* use corrected math; the 100% transcription bug is isolated in Table 1. This baseline is **not** the product default.

### 3.4 Product integrity

Consent before data entry; export/delete; OAuth with refresh + optional Fernet token sealing; homepage copy aligned with ledger; `ml/` quarantined.

---

## 4. Evaluation

### 4.1 Equation fidelity (Table 1)

White-female PCE reference (age 55, TC 213, HDL 50, SBP 120 untreated, nonsmoker, nondiabetic):

| Implementation | Risk |
|---|---|
| Buggy transcription (reconstructed) | **100%** |
| Corrected Drift PCE | **2.1%** |

PREVENT golden (Khan/CVrisk worked examples): female high-risk ASCVD target **9.2%** (Drift within 0.35pp); male base ≈**2.9%** (within 0.4pp). Source: `tests/test_prevent_golden.py`.

### 4.2 NHANES disclosure disparity (Table 2)

NHANES 2017–March 2020 public XPT (DEMO/BPXO/BMX/HDL/TCHOL/BIOPRO/SMQ/DIQ/BPQ); adults 30–79; seed-42 subsample n=2500.

**Construction note.** For races ∉ {White, AA}, legacy White-fallback rate **among PCE-scored profiles is 1.0 by design**. NHANES’s contribution is (a) **how many people** that policy touches, and (b) **honest coverage cost** by stratum under observed missingness.

| Stratum | n | Lab-complete | Honest show | Misattributed PCE count (legacy) | Fallback among PCE-scored |
|---|---:|---:|---:|---:|---:|
| White | 803 | 0.82 | 0.65 | 0 | 0.00 |
| African American | 679 | 0.75 | 0.55 | 0 | 0.00 |
| Hispanic | 562 | 0.77 | 0.65 | **405** | **1.00** |
| Asian (RIDRETH3=6; all NHA) | 336 | 0.73 | 0.65 | **228** | **1.00** |
| Multiracial/other | 120 | 0.78 | 0.64 | **77** | **1.00** |

After removing the erroneous ASCVD BMI refuse gate (ASCVD BMI coefficients are 0.0), honest show rates rise (White ≈0.76, AA ≈0.66, Hispanic ≈0.71). Remaining AA gap is dominated by missing SBP / lipids / compute-range gates (see refuse_gates in `nhanes_coverage_audit.json`), not ethnicity remapping. When both arms produce a numeric, band reclassification rates are substantial (e.g. AA ≈0.61, White ≈0.47)—the clinical-threshold distortion of legacy disclosure, not only a count of fallbacks. eGFR uses **2021 race-free CKD-EPI**. Limitations: seed-pinned subsample with WTMEC4YR within-subsample weights; no mortality calibration; Asian not South/East-split.

### 4.3 Shared-key vignette evaluation (Table 3)

Seventeen fixtures (study vignettes + race×sex grid + missing-SBP). Both arms scored on the same keys; mutation tests inject each failure into honest outputs and require the scorer to catch them (`all_caught=true`).

| Honesty key | Honest | Legacy | Δ |
|---|---:|---:|---:|
| No White-PCE fallback | 1.00 | 0.47 | +0.53 |
| No green under-40 | 1.00 | 0.94 | +0.06 |
| No silent waist | 1.00 | 0.94 | +0.06 |
| No silent SBP | 1.00 | 0.94 | +0.06 |
| No cancer-RR hero | 1.00 | 0.00 | +1.00 |
| No health-age hero | 1.00 | 0.00 | +1.00 |
| Shows estimate when complete | 1.00 | 1.00 | 0.00 |
| **Mean (all keys)** | **1.00** | **0.61** | **+0.39** |
| **Mean (core keys\*)** | **1.00** | **0.86** | **+0.14** |

\*Core excludes cancer-RR and health-age (always-on in legacy by design). White-fallback remains the material intermediate gap. Wilson 95% CIs in `vignette_eval.json`.

### 4.4 Human study (preregistered; not fielded)

Protocol: `study/PROTOCOL.md` · OSF draft: `study/osf/preregistration.json` · IRB packet: `study/IRB_EXEMPTION_REQUEST.md` · Power: d=0.25 → ≈252/arm (target 300/arm; `power_analysis.json`).

Instrument frozen to PROTOCOL/OSF 1.1: server-side SQLite assignment (opaque token; arm not in cookie), engine-rendered cards, no care-seeking CTA in stimulus, server-issued completion codes, no IP logging, study DB separate from `users.db`, product UI cannot enable baseline without `STUDY_ALLOW_BASELINE=1`. Primary endpoint remains **unanswered** until IRB + recruitment — we do not substitute computational checks for human trust.

---

## 5. Discussion & limitations

Executable contracts make ethics docs falsifiable. The legacy baseline answers the “self-inflicted bug” critique by pinning failure modes to a git SHA. Under that policy, fallback among PCE-scored non-White/non-AA profiles is 1.0 by construction; NHANES’s contribution is the **burden count** (710 misattributed scores in a 2500-adult subsample: 405 Hispanic, 228 Asian, 77 multiracial) and the honest arm’s coverage cost by stratum.

**Limitations.** PREVENT coeffs follow PyPREVENT / Khan S12 lineage with golden cross-checks, not a multi-site clinical validation. FINDRISC is European-derived. Binary equation sex. No NHANES mortality calibration. Single-developer positionality. Without fielded humans, trust/anchoring claims stay provisional. Expert LLM walkthrough is exploratory only.

**Ethics.** Special-category data in the product path; study path uses fictional vignettes. Consent; educational labeling; no diagnostic marketing.

---

## 6. Conclusion

Drift attacks consumer health-risk harms at the disclosure layer: contracts, refusal, race-free defaults that remove White fallback by policy, NHANES burden counts under the legacy policy, and a measurable honesty-key gap versus a git-pinned legacy UI. We release the artifact and a field-ready protocol for the remaining human question.

---

## References

1. Vyas DA et al. Hidden in Plain Sight. *NEJM* 2020.  
2. Yadlowsky S et al. Revised PCE implications. *Ann Intern Med* 2018.  
3. Goff DC et al. 2013 ACC/AHA risk guideline. *Circulation* 2014.  
4. Gigerenzer G et al. Helping doctors and patients make sense of health statistics. *Psychol Sci Public Interest* 2007.  
5. Fagerlin A, Zikmund-Fisher BJ, Ubel PA. Helping patients decide: ten steps to better risk communication. *JNCI* 2011.  
6. Ancker JS et al. Design features of graphs in health risk communication: a systematic review. *JAMIA* 2006.  
7. Mitchell M et al. Model Cards. *FAccT* 2019.  
8. Gebru T et al. Datasheets for Datasets. *CACM* 2021.  
9. Chow C. On optimum recognition error and reject tradeoff. *IEEE Trans IT* 1970.  
10. Khan SS et al. AHA PREVENT equations. *Circulation* 2024.  
11. Hullman J, Kay M. Uncertainty visualization / graphical inference. *IEEE TVCG* (survey line).  
12. FDA. Clinical Decision Support Software guidance; SaMD guidance.  
13. Lindström J, Tuomilehto J. FINDRISC. *Diabetes Care* 2003.  
14. Arnold M et al. FactSheets / usage documentation for AI services (IBM / follow-ons).  
15. Diao JA et al. Clinical implications of removing race from eGFR equations. *NEJM* 2021.  
16. Obermeyer Z et al. Dissecting racial bias in an algorithm used to manage the health of populations. *Science* 2019.  
17. Raji ID et al. Closing the AI accountability gap. *FAccT* 2020.  
18. Chen IY et al. Ethical machine learning in healthcare. *Annu Rev Biomed Data Sci* 2021.

---

## Appendix — Reproduce

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pandas numpy flask pytest
pytest -q
python scripts/validate_claims.py
python scripts/baseline_git_pin.py
python scripts/eval_vignettes.py
# NHANES XPTs under data/nhanes/ (gitignored); then:
python scripts/nhanes_coverage_audit.py
python scripts/power_analysis.py
python app_v5.py  # /study/prolific  /study/collect  ?mode=honest|baseline
```

Artifact paths: `legacy_baseline.py`, `risk_engine.py`, `claims.yaml`, `study/`, `cards/SYSTEM_CARD.md`, `ml/QUARANTINE.md`, `docs/facct/`.
