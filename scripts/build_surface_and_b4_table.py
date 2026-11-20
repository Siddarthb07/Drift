#!/usr/bin/env python3
"""B1 surface reframe + B4 coding-bug vs mislabeled-model classification."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OSS = ROOT / "docs" / "jbhi" / "outside_corpus"
DIFF = json.loads((OSS / "oss_differential_report.json").read_text())
MANUAL = json.loads((OSS / "transcription_handcheck_manual.json").read_text())
OUT = OSS / "surface_b4_report.json"

# Surface taxonomy for the 17 runnable adapters
SURFACE = {
    "Articulus-Tech_ascvd": "library",
    "babuljack_ascvdrisk": "app",  # Django app wrapping Articulus-like core
    "InterconnectedSystems_prevent-calculator": "library",
    "abusuraihsakhri_ascvd-risk-calculator": "library",
    "maher-coder_prevent-benchmark": "library",
    "MedicoAssassino_PREVENT-AHA-calculator-api": "library",  # API/library
    "Adoracion2020_Framingham-risk-calculator": "library",
    "abusuraihsakhri_framingham-risk-calculator": "library",
    "asifali015_Framingham-CVD-Risk-Calculator": "cli",
    "alinayu03_ASCVD-Risk": "app",  # Streamlit
    "onedocfry_ASCVD-Risk-Calculatir": "app",  # Streamlit
    "Fridsma_ASCVD_RiskCalculator": "app",  # Streamlit
    "RonApplePAC_ascvd_calculator": "library",  # JS module
    "bbylw_ascvd-calculator": "app",  # browser UI
    "sueinchoi_ascvd-calculator": "library",  # pure TS lib + SPA
    "MalsTheDev_Framingham-Cardiovascular-Risk-Calculator": "cli",
    "AggelosKrs_framingham-risk-calculator-c": "cli",
}

# B4: per coding-bug / mislabeled with exact line pointers (from prior hand audit)
B4_ROWS = [
    {
        "adapter": "Articulus-Tech_ascvd",
        "surface": "library",
        "family": "pce",
        "silent_white_no_caveat": True,
        "machine_readable_coverage_signal": False,
        "anchor_class": "pass",
        "bug_class": None,
        "line_evidence": "ASCVD() coerces non-{white,aa} to white without returning a caveat field",
    },
    {
        "adapter": "babuljack_ascvdrisk",
        "surface": "app",
        "family": "pce",
        "silent_white_no_caveat": True,
        "machine_readable_coverage_signal": False,
        "anchor_class": "pass",
        "bug_class": None,
        "line_evidence": "App/core.py ASCVD fork: same silent coerce as Articulus",
    },
    {
        "adapter": "abusuraihsakhri_ascvd-risk-calculator",
        "surface": "library",
        "family": "pce",
        "silent_white_no_caveat": True,
        "machine_readable_coverage_signal": False,
        "anchor_class": "pass",
        "bug_class": None,
        "line_evidence": "ascvd_pooled_cohort.py maps non-AA→white group; return object has no caveat field",
    },
    {
        "adapter": "RonApplePAC_ascvd_calculator",
        "surface": "library",
        "family": "pce",
        "silent_white_no_caveat": True,
        "machine_readable_coverage_signal": False,
        "anchor_class": "pass",
        "bug_class": None,
        "line_evidence": "src/pce.js calculateRisk: race==='other'→white equations; returns bare number (comment ≠ output)",
    },
    {
        "adapter": "sueinchoi_ascvd-calculator",
        "surface": "library",
        "family": "pce",
        "silent_white_no_caveat": True,
        "machine_readable_coverage_signal": False,
        "anchor_class": "pass",
        "bug_class": None,
        "line_evidence": "selectGroup(sex, race) only white|africanAmerican; Other coerced without caveat in PceResult",
    },
    {
        "adapter": "alinayu03_ASCVD-Risk",
        "surface": "app",
        "family": "pce",
        "silent_white_no_caveat": True,
        "machine_readable_coverage_signal": False,
        "anchor_class": "pass",
        "bug_class": None,
        "line_evidence": "main.py: race=='White' or 'Other' share White coefficients; return is bare float",
    },
    {
        "adapter": "Fridsma_ASCVD_RiskCalculator",
        "surface": "app",
        "family": "pce",
        "silent_white_no_caveat": True,
        "machine_readable_coverage_signal": False,
        "anchor_class": "coding_bug",
        "bug_class": "wrong_coefficients_non_goff",
        "line_evidence": "main.py calculate_ascvd_risk: non-Goff coef vector; worked examples → ~100%",
    },
    {
        "adapter": "onedocfry_ASCVD-Risk-Calculatir",
        "surface": "app",
        "family": "pce",
        "silent_white_no_caveat": False,  # other→white-male so female other ≠ female white
        "machine_readable_coverage_signal": False,
        "anchor_class": "coding_bug",
        "bug_class": "cancelled_centering_sum_minus_sum",
        "line_evidence": "ascvd_calculator_pro.py: risk = 1 - baseline ** exp(sum_terms - sum_terms); else→white-male coeffs",
    },
    {
        "adapter": "bbylw_ascvd-calculator",
        "surface": "app",
        "family": "pce",
        "silent_white_no_caveat": True,
        "machine_readable_coverage_signal": False,
        "anchor_class": "mislabeled_model",
        "bug_class": "heuristic_race_multipliers_not_pce",
        "line_evidence": "script.js calculateRisk: sex-only coeffs + asian×0.5 / aa×1.3; not Goff PCE",
    },
    {
        "adapter": "InterconnectedSystems_prevent-calculator",
        "surface": "library",
        "family": "prevent",
        "silent_white_no_caveat": False,
        "machine_readable_coverage_signal": True,  # race-free by design
        "anchor_class": "coding_bug",
        "bug_class": "sex_argument_ignored",
        "line_evidence": "prevent_calculator.calculate_risk: male profile returns female ASCVD 9.195 not 10.2",
    },
    {
        "adapter": "maher-coder_prevent-benchmark",
        "surface": "library",
        "family": "prevent",
        "silent_white_no_caveat": False,
        "machine_readable_coverage_signal": True,
        "anchor_class": "pass",
        "bug_class": None,
        "line_evidence": "Matches preventr canonical ASCVD to 3 decimals",
    },
    {
        "adapter": "MedicoAssassino_PREVENT-AHA-calculator-api",
        "surface": "library",
        "family": "prevent",
        "silent_white_no_caveat": False,
        "machine_readable_coverage_signal": True,
        "anchor_class": "harness_exclude",
        "bug_class": "php_port_delta",
        "line_evidence": "PHP→Python port Δ0.54pp on male anchor; excluded from extraordinary claim",
    },
]

# Framingham rows: mislabeled if presented as ASCVD/PCE in README else equation_family_ok
for name in [
    "Adoracion2020_Framingham-risk-calculator",
    "abusuraihsakhri_framingham-risk-calculator",
    "asifali015_Framingham-CVD-Risk-Calculator",
    "MalsTheDev_Framingham-Cardiovascular-Risk-Calculator",
    "AggelosKrs_framingham-risk-calculator-c",
]:
    B4_ROWS.append({
        "adapter": name,
        "surface": SURFACE[name],
        "family": "framingham",
        "silent_white_no_caveat": False,
        "machine_readable_coverage_signal": False,  # no race coverage signal relevant
        "anchor_class": "mislabeled_or_other_equation",
        "bug_class": "framingham_not_pce_prevent_anchor",
        "line_evidence": "Framingham/CVD points or continuous model — not scored against PCE/PREVENT anchors",
    })

by_surface = {}
for r in B4_ROWS:
    by_surface.setdefault(r["surface"], []).append(r)

libs = [r for r in B4_ROWS if r["surface"] == "library"]
lib_sw = [r for r in libs if r["silent_white_no_caveat"] and r["family"] == "pce"]
no_signal = [r for r in B4_ROWS if r["family"] == "pce" and not r["machine_readable_coverage_signal"] and r["silent_white_no_caveat"]]

coding = [r for r in B4_ROWS if r["anchor_class"] == "coding_bug"]
mislabeled = [r for r in B4_ROWS if r["anchor_class"] in ("mislabeled_model", "mislabeled_or_other_equation")]

report = {
    "b1_reframe": {
        "claim": "Primary finding reframed: among race-stratified PCE surfaces, no machine-readable coverage signal when Other→White numeric equality holds",
        "by_surface_counts": {k: len(v) for k, v in by_surface.items()},
        "library_pce_silent_white_no_caveat": f"{len(lib_sw)}/{len([r for r in libs if r['family']=='pce'])}",
        "pce_no_machine_readable_coverage_signal": len(no_signal),
        "n_pce": len([r for r in B4_ROWS if r["family"] == "pce"]),
    },
    "b4_classification": {
        "coding_bugs": len(coding),
        "mislabeled_or_other_equation": len(mislabeled),
        "harness_exclude": sum(1 for r in B4_ROWS if r["anchor_class"] == "harness_exclude"),
        "pass": sum(1 for r in B4_ROWS if r["anchor_class"] == "pass"),
    },
    "per_adapter": B4_ROWS,
    "manual_handcheck_sha256": hashlib.sha256(
        (OSS / "transcription_handcheck_manual.json").read_bytes()
    ).hexdigest()[:16],
}

OUT.write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({k: report[k] for k in ("b1_reframe", "b4_classification")}, indent=2))
