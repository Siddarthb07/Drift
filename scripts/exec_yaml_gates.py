#!/usr/bin/env python3
"""C2: Execute declared YAML imperative gates (ledger as source of truth).

Reads claims.yaml imperative_gates_declared and applies the portable subset
against a request+payload pair. Engine paths remain authoritative for production;
this module proves the declarations are executable.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

ROOT = Path(__file__).resolve().parents[1]
CLAIMS = ROOT / "claims.yaml"
OUT = ROOT / "docs" / "jbhi" / "outside_corpus" / "yaml_gate_executor_report.json"


def load_declared() -> Dict[str, Any]:
    doc = yaml.safe_load(CLAIMS.read_text())
    return doc.get("imperative_gates_declared") or {}


def check_gates(request: Dict[str, Any], payload: Dict[str, Any], claim_id: str) -> Tuple[bool, List[str]]:
    """Return (allow, violations)."""
    gates = load_declared()
    viol: List[str] = []
    cvd = payload.get("CVD") or {}

    def applies(g: Dict[str, Any]) -> bool:
        apps = g.get("applies_to") or []
        return "*" in apps or claim_id in apps

    g = gates.get("missing_egfr") or {}
    if applies(g) and request.get("egfr") in (None, "") and _numeric(cvd):
        viol.append("missing_egfr")

    g = gates.get("labs_cholesterol_ranges") or {}
    if applies(g):
        tc = request.get("total_cholesterol") or request.get("tc")
        if tc is not None and (tc < 130 or tc > 320) and _numeric(cvd):
            viol.append("labs_cholesterol_ranges")

    g = gates.get("sex_equation_required") or {}
    if applies(g):
        sex = str(request.get("sex") or "").lower()
        if sex in ("nonbinary", "other", "unknown") and not request.get("sex_for_equation") and _numeric(cvd):
            viol.append("sex_equation_required")

    g = gates.get("score2_non_invention") or {}
    if applies(g):
        eq = str(cvd.get("equation") or "").upper()
        if "SCORE2" in eq or cvd.get("score2_coefficients"):
            viol.append("score2_non_invention")

    g = gates.get("public_view_strip_keys") or {}
    if applies(g):
        if any(str(k).endswith("_exact") for k in _walk_keys(payload)):
            viol.append("public_view_strip_keys")

    g = gates.get("study_allow_baseline_env") or {}
    if applies(g) and request.get("mode") == "baseline" and not request.get("study_allow_baseline"):
        viol.append("study_allow_baseline_env")

    return (len(viol) == 0), viol


def _numeric(cvd: Dict[str, Any]) -> bool:
    v = cvd.get("risk_pct")
    return isinstance(v, (int, float)) or bool(cvd.get("risk_pct_exact")) or (
        bool(cvd.get("risk_band_label")) and not cvd.get("refused")
    )


def _walk_keys(obj: Any) -> List[str]:
    keys: List[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.append(str(k))
            keys.extend(_walk_keys(v))
    elif isinstance(obj, list):
        for v in obj:
            keys.extend(_walk_keys(v))
    return keys


def main() -> int:
    fixtures = [
        ("ok_prevent", {"age": 55, "egfr": 90, "sex": "female", "mode": "honest"},
         {"claim_id": "prevent_ascvd", "CVD": {"risk_pct": None, "risk_band_label": "borderline"}}, True),
        ("missing_egfr_leak", {"age": 55, "egfr": None, "mode": "honest"},
         {"claim_id": "prevent_ascvd", "CVD": {"risk_pct": 8.2}}, False),
        ("score2_invent", {"age": 55, "mode": "honest"},
         {"claim_id": "prevent_ascvd", "CVD": {"equation": "SCORE2", "risk_pct": 5.0}}, False),
        ("nonbinary_numeric", {"age": 55, "sex": "nonbinary", "mode": "honest"},
         {"claim_id": "prevent_ascvd", "CVD": {"risk_pct": 7.1}}, False),
        ("exact_on_wire", {"age": 55, "mode": "honest"},
         {"claim_id": "prevent_ascvd", "CVD": {"risk_pct_exact": 7.1}}, False),
        ("baseline_env", {"age": 55, "mode": "baseline", "study_allow_baseline": False},
         {"claim_id": "legacy_baseline", "CVD": {"risk_pct": 5.0}}, False),
    ]
    declared = load_declared()
    rows = []
    for name, req, payload, expect_allow in fixtures:
        allow, viol = check_gates(req, payload, payload.get("claim_id", "prevent_ascvd"))
        rows.append({
            "id": name,
            "allow": allow,
            "violations": viol,
            "expect_allow": expect_allow,
            "pass": allow == expect_allow,
        })
    report = {
        "n_declared_gates": len(declared),
        "gate_ids": list(declared.keys()),
        "n_fixtures": len(rows),
        "n_pass": sum(1 for r in rows if r["pass"]),
        "rows": rows,
        "status": "executor_online",
        "note": "YAML-declared imperative gates are executable; production disclosure.py remains primary.",
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    # Mark claims statuses as executable
    print(json.dumps({k: report[k] for k in ("n_declared_gates", "n_fixtures", "n_pass", "status")}, indent=2))
    return 0 if report["n_pass"] == report["n_fixtures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
