# FAccT 2027 — Abstract (OpenReview registration)

**Title:** Executable Disclosure Contracts for Consumer Health-Risk Interfaces

**Focus areas:** System development and deployment; Evaluations and evaluation practices

**Abstract (≤2000 chars — paste into OpenReview):**

Consumer health applications compile published risk equations into user interfaces. In that product path, harms often arise from disclosure policy—silent imputation of missing labs, routing unsupported racial categories through White-specific coefficients, and false-precision “biological age” heroes—rather than from training a new model. We introduce executable disclosure contracts: a machine-readable claim ledger bound to runtime display policy (band, refuse, or factors-only), enforced on the serving path.

We implement the contract in Drift, an open educational health tracker. The default cardiovascular path uses the race-free AHA PREVENT equations so users across racial and ethnic labels share one calculator without invented ethnicity multipliers; optional Pooled Cohort Equations are limited to validated White and African American cohorts. A pinned legacy baseline reconstructs prior disclosure failures for controlled comparison. Computationally, a reconstructed PCE transcription bug yields 100% ten-year risk on a standard White-female reference profile versus 2.1% after correction; shared-key honesty evaluation across sixteen fixtures scores 1.00 (honest) versus 0.56 (legacy baseline). Missing-eGFR refusal is uniform across race strata, documenting a coverage cost of honesty. We release Drift, audits, and a Prolific-ready vignette protocol; fielded human results are the next step and are not claimed here. Drift is educational decision support, not a medical device.

**Keywords:** accountability, health risk communication, disclosure policy, PREVENT, abstention, consumer health UI

**Conflicts / anonymization:** Anonymize GitHub links for review; artifact available upon request / anonymous supplementary ZIP.

**Human subjects:** Protocol prepared; fielding pending IRB/exemption. Abstract does not report human outcome data.
