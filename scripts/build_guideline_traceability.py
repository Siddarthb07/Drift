#!/usr/bin/env python3
"""A2: Guideline traceability matrix — each ledger rule → cited clause or design choice."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "jbhi" / "outside_corpus" / "guideline_traceability.json"
COV = ROOT / "docs" / "facct" / "ledger_coverage.json"

# Explicit rule → guideline mapping (page/clause citations where known)
RULES = [
    # PCE
    {"rule_id": "pce.race_in_white_aa", "claim": "pce_ascvd", "kind": "requires.race_in",
     "trace": "guideline", "source": "Goff 2013/2014 ACC/AHA", "clause": "PCE validated for White and African American adults; Other race guidance is apply White equations with under/overestimate caveat (ACC Estimator documents this).", "page": "Circulation 2014;129:S49–S73; ACC Risk Estimator Plus UI"},
    {"rule_id": "pce.age_40_79", "claim": "pce_ascvd", "kind": "requires.age",
     "trace": "guideline", "source": "Goff 2013/2014", "clause": "PCE intended age range 40–79 years.", "page": "Goff Appendix / ACC tool age bounds"},
    {"rule_id": "pce.require_sbp", "claim": "pce_ascvd", "kind": "requires.any_of_fields",
     "trace": "guideline", "source": "Goff 2013/2014", "clause": "Systolic BP is a required input to PCE; missing BP is not a validated silent default.", "page": "Equation inputs"},
    {"rule_id": "pce.no_white_fallback_undisclosed", "claim": "pce_ascvd", "kind": "prohibited_uses",
     "trace": "guideline", "source": "Goff/ACC Estimator", "clause": "Other→White coefficient use must be disclosed (ACC tool shows under/overestimate note). Silent remap without disclosure is the violation class.", "page": "ACC Risk Estimator Plus Other-race note"},
    {"rule_id": "pce.consumer_band", "claim": "pce_ascvd", "kind": "audience_policies.consumer",
     "trace": "design_choice", "source": None, "clause": "Banding exact percents on consumer surfaces — risk-communication design, not a Goff mandate.", "page": None},
    {"rule_id": "pce.clinician_number", "claim": "pce_ascvd", "kind": "audience_policies.clinician",
     "trace": "design_choice", "source": None, "clause": "Allow clinician exacts to avoid over-refusal of calculator-style UIs.", "page": None},
    # PREVENT
    {"rule_id": "prevent.age_30_79", "claim": "prevent_ascvd", "kind": "requires.age",
     "trace": "guideline", "source": "Khan 2024 PREVENT", "clause": "PREVENT equations intended for ages 30–79.", "page": "Circulation 2024 PREVENT methods"},
    {"rule_id": "prevent.require_sbp", "claim": "prevent_ascvd", "kind": "requires.any_of_fields",
     "trace": "guideline", "source": "Khan 2024", "clause": "SBP required; race-free by design.", "page": "PREVENT base model inputs"},
    {"rule_id": "prevent.consumer_band", "claim": "prevent_ascvd", "kind": "audience_policies.consumer",
     "trace": "design_choice", "source": None, "clause": "Consumer banding of PREVENT exacts.", "page": None},
    {"rule_id": "prevent.clinician_number", "claim": "prevent_ascvd", "kind": "audience_policies.clinician",
     "trace": "design_choice", "source": None, "clause": "Clinician exacts allowed.", "page": None},
    {"rule_id": "prevent.no_diagnosis", "claim": "prevent_ascvd", "kind": "prohibited_uses",
     "trace": "guideline", "source": "Khan 2024 / FDA CDS spirit", "clause": "Risk estimate is not a diagnosis or treatment order.", "page": "Intended-use framing"},
    # FINDRISC
    {"rule_id": "findrisc.no_silent_waist", "claim": "findrisc", "kind": "prohibited_uses",
     "trace": "guideline", "source": "Lindström & Tuomilehto 2003", "clause": "Waist circumference is a scored input; silent sex-default waist invents a score.", "page": "Diabetes Care 2003 FINDRISC"},
    {"rule_id": "findrisc.no_collapse_interval", "claim": "findrisc", "kind": "prohibited_uses",
     "trace": "design_choice", "source": None, "clause": "When waist missing, show interval rather than mid-point — disclosure design.", "page": None},
    # Cancer / heuristics
    {"rule_id": "cancer.factors_only", "claim": "cancer_lifestyle_factors", "kind": "display_policy",
     "trace": "guideline", "source": "WCRF/AICR 2018", "clause": "Factor-level evidence only; no validated multi-cancer absolute risk product from this list.", "page": "WCRF/AICR recommendations"},
    {"rule_id": "cancer.no_compounded_rr", "claim": "cancer_lifestyle_factors", "kind": "prohibited_uses",
     "trace": "design_choice", "source": None, "clause": "Block compounded RR gauge — product-safety design beyond WCRF text.", "page": None},
    {"rule_id": "health_age.refuse", "claim": "health_age_heuristic", "kind": "display_policy",
     "trace": "design_choice", "source": None, "clause": "Heuristic health-age is unpublished; refuse numeric display.", "page": None},
    {"rule_id": "lifestyle.qualitative", "claim": "lifestyle_trajectory", "kind": "display_policy",
     "trace": "design_choice", "source": None, "clause": "Local habit log is qualitative only.", "page": None},
    # BP domain
    {"rule_id": "bp.category_qualitative", "claim": "bp_category_acc2017", "kind": "display_policy",
     "trace": "guideline", "source": "Whelton ACC/AHA 2017", "clause": "Office BP categories (Normal/Elevated/Stage 1/2) are guideline labels, not a CVD equation.", "page": "Hypertension 2018 guideline"},
    {"rule_id": "bp.require_age_18", "claim": "bp_category_acc2017", "kind": "requires.age",
     "trace": "guideline", "source": "Whelton 2017", "clause": "Adult BP guideline context.", "page": "Adult guideline scope"},
    {"rule_id": "bp.no_silent_impute", "claim": "bp_category_acc2017", "kind": "prohibited_uses",
     "trace": "guideline", "source": "Whelton 2017", "clause": "Category requires measured SBP/DBP; silent 120/80 invents a category.", "page": "Measurement / classification sections"},
    {"rule_id": "bp.factors_only", "claim": "bp_modifiable_factors", "kind": "display_policy",
     "trace": "guideline", "source": "ACC/AHA 2017 lifestyle", "clause": "Lifestyle factor list without absolute risk product.", "page": "Lifestyle recommendations"},
    {"rule_id": "bp.home_avg_refuse", "claim": "bp_home_average_heuristic", "kind": "display_policy",
     "trace": "design_choice", "source": None, "clause": "Unpublished home-average heuristic refused (not ABPM/HBPM protocol).", "page": None},
    # Imperative gates documented as rules
    {"rule_id": "gate.missing_egfr", "claim": "prevent_ascvd", "kind": "imperative_engine",
     "trace": "guideline", "source": "Khan 2024", "clause": "eGFR is a PREVENT input; missing eGFR blocks PREVENT numeric.", "page": "PREVENT inputs"},
    {"rule_id": "gate.labs_cholesterol", "claim": "prevent_ascvd", "kind": "imperative_engine",
     "trace": "guideline", "source": "Khan 2024 / Goff", "clause": "TC/HDL required within calculator ranges.", "page": "Published calculator ranges"},
    {"rule_id": "gate.sex_equation", "claim": "*", "kind": "imperative_engine",
     "trace": "guideline", "source": "Goff/Khan", "clause": "Sex-specific equations require explicit equation sex.", "page": "Sex-stratified coefficients"},
    {"rule_id": "gate.public_view_strip", "claim": "*", "kind": "imperative_serving",
     "trace": "design_choice", "source": None, "clause": "Strip *_exact from public payloads — serving-path safety design.", "page": None},
    {"rule_id": "gate.fail_closed_unknown_claim", "claim": "*", "kind": "ledger",
     "trace": "design_choice", "source": None, "clause": "Unknown claim_id fails closed.", "page": None},
    {"rule_id": "gate.score2_non_invention", "claim": "*", "kind": "imperative_region",
     "trace": "guideline", "source": "SCORE2 literature", "clause": "Do not invent unsupported regional equations.", "page": "Region coverage notes"},
    {"rule_id": "gate.baseline_env", "claim": "legacy_baseline", "kind": "imperative_serving",
     "trace": "design_choice", "source": None, "clause": "Unconstrained baseline gated by study env flag.", "page": None},
    {"rule_id": "gate.bmi_caveat_not_refuse", "claim": "prevent_ascvd", "kind": "imperative_engine",
     "trace": "guideline", "source": "Khan 2024", "clause": "Base ASCVD BMI coefficients are zero; OOR BMI → caveat rather than hard refuse on ASCVD path.", "page": "PREVENT base model"},
    {"rule_id": "legacy.study_only", "claim": "legacy_baseline", "kind": "prohibited_uses",
     "trace": "design_choice", "source": None, "clause": "Legacy arm is experimental control only.", "page": None},
]

def main() -> int:
    n_g = sum(1 for r in RULES if r["trace"] == "guideline")
    n_d = sum(1 for r in RULES if r["trace"] == "design_choice")
    report = {
        "n_rules": len(RULES),
        "n_guideline_traced": n_g,
        "n_design_choice": n_d,
        "summary_sentence": f"{n_g}/{len(RULES)} rules trace to guideline text; {n_d} are design choices with no guideline basis.",
        "design_choices": [r for r in RULES if r["trace"] == "design_choice"],
        "guideline_traced": [r for r in RULES if r["trace"] == "guideline"],
        "all_rules": RULES,
    }
    if COV.exists():
        report["ledger_coverage_artifact"] = str(COV.relative_to(ROOT))
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("n_rules", "n_guideline_traced", "n_design_choice", "summary_sentence")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
