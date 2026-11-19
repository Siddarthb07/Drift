#!/usr/bin/env python3
"""
Literature-derived enforcement probe (primary novelty stress test).

Unlike V1–V17, oracles are specified from published risk-communication / CDS /
race-correction sources and scored on public payloads without requiring
Drift-specific flags (e.g. legacy_white_fallback).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from disclosure import DisclosureError, apply_disclosure, public_view  # noqa: E402
from risk_engine import compute_risk_scores  # noqa: E402

OPA = ROOT / ".tools" / "opa"
REGO = ROOT / "policies" / "public_payload.rego"
SPEC = ROOT / "docs" / "facct" / "literature_derived_violations.json"
OUT = ROOT / "docs" / "facct" / "literature_derived_probe.json"

DAILY = [{"sleep": 7, "steps": 9000, "stress_level": 4, "active_minutes": 30,
          "veg_servings": 3, "fruit_servings": 2, "red_meat_servings": 1, "processed_meat": 0}] * 14
LABS = {"total_cholesterol": 210, "hdl_cholesterol": 55, "egfr": 90}


def _user(**kw):
    u = dict(age=55, sex="female", sex_for_equation="female", height=165, weight=70,
             waist_cm=80, systolic=128, race="white", smoking_status="never",
             bp_medication=0, existing_diabetes=0, high_glucose_history=0,
             family_history_diabetes=0, family_history_cancer=0, alcohol_per_week=0,
             region="global")
    u.update(kw)
    return u


def _has_exact(obj: Any) -> bool:
    if isinstance(obj, dict):
        if any(str(k).endswith("_exact") for k in obj):
            return True
        return any(_has_exact(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_exact(x) for x in obj)
    return False


def _cvd_numeric(cvd: dict) -> bool:
    if cvd.get("refused"):
        return False
    return cvd.get("risk_pct") is not None or cvd.get("risk_pct_exact") is not None or bool(
        cvd.get("risk_band_label")
    )


def _drop_nulls(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _drop_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_drop_nulls(v) for v in obj]
    return obj


def _rego_allow(payload: dict) -> bool:
    if not OPA.exists():
        return False
    payload = _drop_nulls(deepcopy(payload))
    with tempfile.TemporaryDirectory() as td:
        inp = Path(td) / "in.json"
        inp.write_text(json.dumps(payload))
        proc = subprocess.run(
            [str(OPA), "eval", "-f", "values", "-d", str(REGO), "-i", str(inp),
             "data.drift.public_payload.allow"],
            capture_output=True, text=True, timeout=30,
        )
        return any(line.strip() == "true" for line in (proc.stdout or "").splitlines())


def _schema_ok(payload: dict) -> bool:
    payload = _drop_nulls(deepcopy(payload))
    if _has_exact(payload) or "health_age" in payload:
        return False
    canc = payload.get("Cancer") or {}
    if isinstance(canc, dict) and "relative_risk" in canc:
        return False
    diab = payload.get("Diabetes") or {}
    if isinstance(diab, dict) and diab.get("score_range") and isinstance(diab.get("risk_pct"), (int, float)):
        return False
    return True


def _oracle_violation_present(vid: str, pub: dict) -> bool:
    """True if the literature-prohibited condition is present on the public object."""
    cvd = pub.get("CVD") or {}
    if vid == "L1":
        return cvd.get("risk_pct") is not None or cvd.get("risk_pct_exact") is not None
    if vid == "L2":
        return str(cvd.get("equation") or "").upper() == "PCE" and _cvd_numeric(cvd)
    if vid == "L3":
        return pub.get("health_age") is not None or (
            isinstance(pub.get("Cancer"), dict) and pub["Cancer"].get("relative_risk") is not None
        )
    if vid == "L4":
        return _cvd_numeric(cvd) and not cvd.get("refused")
    if vid == "L5":
        return False  # scored via exception path
    if vid == "L6":
        green = "Under 40" in str(cvd.get("risk_category") or "") or (
            cvd.get("color") == "green" and not cvd.get("refused")
        )
        return green or _cvd_numeric(cvd)
    if vid == "L7":
        return cvd.get("risk_pct") is not None or _has_exact(cvd)
    if vid == "L8":
        diab = pub.get("Diabetes") or {}
        return bool(diab.get("score_range")) and diab.get("risk_pct") is not None
    return True


def _build_leaky(vid: str) -> Tuple[dict, bool]:
    """Return (public_candidate, exception_caught_for_L5)."""
    if vid == "L1":
        return public_view(compute_risk_scores(_user(), DAILY, LABS, mode="honest")), False
    if vid == "L2":
        return public_view(compute_risk_scores(
            _user(race="south_asian", prefer_pce=True, sex="male", sex_for_equation="male"),
            DAILY, LABS, mode="honest")), False
    if vid == "L3":
        risk = compute_risk_scores(_user(), DAILY, LABS, mode="honest")
        inj = deepcopy(risk)
        inj.setdefault("Cancer", {})["relative_risk"] = 2.4
        canc = apply_disclosure(dict(inj["Cancer"]), mode="honest", claim_id="cancer_lifestyle_factors")
        ha = apply_disclosure({"health_age": 61.0}, mode="honest", claim_id="health_age_heuristic")
        return public_view({"Cancer": canc, "health_age": ha.get("health_age"), "CVD": inj.get("CVD"),
                            "_health_age_block": ha}), False
    if vid == "L4":
        return public_view(compute_risk_scores(_user(systolic=None), DAILY, LABS, mode="honest")), False
    if vid == "L5":
        try:
            apply_disclosure({"risk_pct": 5.0}, mode="honest", claim_id="not_a_real_claim")
            return {"claim_id": "not_a_real_claim", "CVD": {"risk_pct": 5.0}}, False
        except DisclosureError:
            return {"claim_id": "not_a_real_claim"}, True
    if vid == "L6":
        return public_view(compute_risk_scores(_user(age=28), DAILY, LABS, mode="honest")), False
    if vid == "L7":
        risk = compute_risk_scores(_user(), DAILY, LABS, mode="honest")
        cvd = deepcopy(risk["CVD"])
        # Simulate leaky API reinjection then contract cleanup path for contract arm
        cvd["risk_pct"] = cvd.get("risk_pct_exact")
        cleaned = apply_disclosure(
            {"risk_pct": cvd["risk_pct"], "age": 55, "race": "white", "sbp": 128,
             "equation": cvd.get("equation")},
            mode="honest", claim_id=cvd.get("claim_id") or "prevent_ascvd",
        )
        return public_view({"CVD": cleaned}), False
    if vid == "L8":
        clean = apply_disclosure(
            {"score_range": [7, 11], "score": 9, "risk_pct": 17.0, "age": 55},
            mode="honest", claim_id="findrisc",
        )
        return public_view({"Diabetes": clean}), False
    return {}, False


def _engine_only_leak(vid: str) -> dict:
    """What reaches the glass without ledger/public_view (leaky adapter)."""
    if vid == "L1":
        return compute_risk_scores(_user(), DAILY, LABS, mode="honest")
    if vid == "L2":
        return compute_risk_scores(
            _user(race="south_asian", prefer_pce=True, sex="male", sex_for_equation="male"),
            DAILY, LABS, mode="honest")
    if vid == "L3":
        risk = compute_risk_scores(_user(), DAILY, LABS, mode="honest")
        risk = deepcopy(risk)
        risk.setdefault("Cancer", {})["relative_risk"] = 2.4
        risk["health_age"] = 61.0
        return risk
    if vid == "L4":
        return compute_risk_scores(_user(systolic=None), DAILY, LABS, mode="honest")
    if vid == "L5":
        return {"claim_id": "not_a_real_claim", "CVD": {"risk_pct": 5.0}}
    if vid == "L6":
        return compute_risk_scores(_user(age=28), DAILY, LABS, mode="honest")
    if vid == "L7":
        risk = compute_risk_scores(_user(), DAILY, LABS, mode="honest")
        cvd = deepcopy(risk["CVD"])
        cvd["risk_pct"] = cvd.get("risk_pct_exact")
        return {"CVD": cvd}
    if vid == "L8":
        return {"Diabetes": {"score_range": [7, 11], "score": 9, "risk_pct": 17.0}}
    return {}


def score_approaches(vid: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    # documentation: always fails to catch (shows leaky)
    leaky = _engine_only_leak(vid)
    if vid == "L5":
        out["documentation_only"] = {"detected": False, "reason": "docs do not execute"}
        out["engine_only"] = {"detected": False, "reason": "engine has no claim-id registry"}
        # contract
        _, caught = _build_leaky(vid)
        out["disclosure_contract"] = {
            "detected": caught,
            "reason": "fail-closed unknown claim_id" if caught else "unknown id accepted",
        }
        out["public_payload_schema"] = {
            "detected": not _schema_ok(leaky),
            "reason": "schema unknown claim_id / structure",
        }
        out["rego_policy"] = {
            "detected": not _rego_allow(leaky),
            "reason": "rego unknown claim_id",
        }
        return out

    viol_leaky = _oracle_violation_present(vid, leaky if vid != "L1" else leaky)
    # L1 leaky engine retains exact → violation present
    if vid == "L1":
        viol_leaky = _has_exact(leaky) or (leaky.get("CVD") or {}).get("risk_pct") is not None

    out["documentation_only"] = {"detected": False, "reason": "docs do not execute"}
    # engine_only: detects only if engine itself already removed the violation
    out["engine_only"] = {
        "detected": not viol_leaky,
        "reason": "engine removed violation" if not viol_leaky else "engine/leaky adapter still shows violation",
    }
    contract_pub, _ = _build_leaky(vid)
    viol_c = _oracle_violation_present(vid, contract_pub)
    out["disclosure_contract"] = {
        "detected": not viol_c,
        "reason": "contract public payload clean" if not viol_c else "violation survived contract",
    }
    out["public_payload_schema"] = {
        "detected": not _schema_ok(leaky),
        "reason": "schema rejects leaky public object" if not _schema_ok(leaky) else "schema allows leaky object",
    }
    out["rego_policy"] = {
        "detected": not _rego_allow(leaky),
        "reason": "rego denies leaky object" if not _rego_allow(leaky) else "rego allows leaky object",
    }
    return out


def main() -> int:
    spec = json.loads(SPEC.read_text())
    matrix = {}
    for case in spec["cases"]:
        matrix[case["id"]] = {
            "source": case["source"],
            "oracle": case["oracle"],
            **score_approaches(case["id"]),
        }
    approaches = ["documentation_only", "engine_only", "public_payload_schema",
                  "rego_policy", "disclosure_contract"]
    n = len(matrix)
    rates = {
        a: sum(1 for vid in matrix if matrix[vid][a]["detected"]) / n
        for a in approaches
    }
    payload = {
        "date": date.today().isoformat(),
        "spec_ref": str(SPEC.relative_to(ROOT)),
        "n_cases": n,
        "detection_rate": rates,
        "matrix": matrix,
        "claim": (
            "Literature-derived oracles (n=8) without Drift flag-keyed detectors. "
            "Still uses Drift as SUT; not third-party authored bugs."
        ),
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({"path": str(OUT.relative_to(ROOT)), "rates": rates}, indent=2))
    # Integrity: contract must catch all literature oracles
    if rates["disclosure_contract"] != 1.0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
