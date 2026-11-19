#!/usr/bin/env python3
"""Probe Drift disclosure contracts against outside-corpus mapped public outputs.

Does not invent violations: each case must come from outputs/*.json with
provenance fields. Reports violations_caught and over_refusals.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("STUDY_ALLOW_BASELINE", "1")

from disclosure import apply_disclosure, public_view, DisclosureError  # noqa: E402

OUT_DIR = ROOT / "docs" / "jbhi" / "outside_corpus" / "outputs"
REPORT = ROOT / "docs" / "jbhi" / "outside_corpus" / "contract_probe_report.json"
SHEET = ROOT / "docs" / "jbhi" / "outside_corpus" / "collection_sheet.csv"


def _is_consumer_violation(meta: Dict[str, Any]) -> bool:
    """Consumer-relevant violation for go/no-go.

    Professional and open-source clinician-style exact percents alone do not count.
    Silent remap/imputation/bio-age count in any arm. Exact percent counts only on
    the consumer arm.
    """
    arm = (meta.get("arm") or "").lower()
    if meta.get("silent_or_undocumented_race_remapping") is True:
        return True
    if meta.get("silent_input_imputation") is True:
        return True
    if meta.get("biological_age_hero") is True:
        return True
    if arm == "consumer" and meta.get("exact_percent_hero_without_uncertainty") is True:
        return True
    return False


def _contract_blocked(out: Dict[str, Any], pub: Dict[str, Any]) -> bool:
    if out.get("refused") or out.get("display_policy") == "refuse":
        return True
    if out.get("shown_as") in ("band", "interval", "factors", "qualitative") and out.get("risk_pct") is None:
        # banded / stripped exact
        if "risk_pct_exact" not in pub and meta_had_exact(out):
            return True
    if "risk_pct_exact" in (out or {}) and "risk_pct_exact" not in pub:
        return True
    if out.get("health_age") is None and out.get("_had_health_age"):
        return True
    return False


def meta_had_exact(out: Dict[str, Any]) -> bool:
    return out.get("risk_pct_exact") is not None or out.get("_input_had_exact")


def probe_one(path: Path) -> Dict[str, Any]:
    blob = json.loads(path.read_text())
    meta = blob.get("meta") or {}
    raw = dict(blob.get("raw_payload") or {})
    claim_id = blob.get("claim_id") or "prevent_ascvd"
    mode = blob.get("mode") or "honest"
    raw["_input_had_exact"] = raw.get("risk_pct") is not None or raw.get("risk_pct_exact") is not None
    if raw.get("health_age") is not None:
        raw["_had_health_age"] = True
    # Keep exact for audit path simulation
    if raw.get("risk_pct") is not None and raw.get("risk_pct_exact") is None:
        raw["risk_pct_exact"] = raw["risk_pct"]
    err = None
    try:
        out = apply_disclosure(raw, mode=mode, claim_id=claim_id)
        pub = public_view(out)
    except DisclosureError as e:
        out = {"refused": True, "gate": "disclosure_error", "note": str(e)}
        pub = public_view(out)
        err = str(e)
    blocked = bool(out.get("refused") or out.get("display_policy") in ("refuse", "band", "interval", "factors_only", "qualitative") and (
        out.get("risk_pct") is None
    ) or ("risk_pct_exact" not in pub and raw.get("risk_pct_exact") is not None) or (raw.get("health_age") is not None and out.get("health_age") is None))
    # clearer blocked semantics
    blocked = bool(
        out.get("refused")
        or out.get("display_policy") == "refuse"
        or (raw.get("risk_pct") is not None and pub.get("risk_pct") is None and pub.get("risk_pct_exact") is None)
        or (raw.get("health_age") is not None and (out.get("health_age") in (None, "") or "health_age" not in pub or pub.get("health_age") is None))
        or (raw.get("relative_risk") is not None and pub.get("relative_risk") is None and out.get("display_policy") == "factors_only")
    )
    consumer_v = _is_consumer_violation(meta)
    intended_valid = bool(meta.get("intended_use_valid_display"))
    over_refusal = bool(blocked and intended_valid and not consumer_v)
    caught = bool(blocked and consumer_v)
    return {
        "tool_id": path.stem,
        "claim_id": claim_id,
        "arm": meta.get("arm"),
        "provenance": meta.get("provenance"),
        "consumer_violation_labeled": consumer_v,
        "intended_use_valid_display": intended_valid,
        "contract_blocked_or_rewrote": blocked,
        "violation_caught": caught,
        "over_refusal": over_refusal,
        "display_policy_out": out.get("display_policy"),
        "refused": out.get("refused"),
        "gate": out.get("gate"),
        "note": out.get("note"),
        "error": err,
        "keys": {k: meta.get(k) for k in (
            "silent_or_undocumented_race_remapping",
            "silent_input_imputation",
            "exact_percent_hero_without_uncertainty",
            "biological_age_hero",
            "refuses_or_warns_on_missing_inputs",
            "documents_coverage_limits_near_estimate",
        )},
    }


def main() -> int:
    cases = sorted(OUT_DIR.glob("*.json"))
    results = [probe_one(p) for p in cases]
    n_caught = sum(1 for r in results if r["violation_caught"])
    n_over = sum(1 for r in results if r["over_refusal"])
    n_consumer_v = sum(1 for r in results if r["consumer_violation_labeled"])
    go = n_caught >= 10
    report = {
        "n_outputs": len(results),
        "n_consumer_violations_labeled": n_consumer_v,
        "violations_caught": n_caught,
        "over_refusals": n_over,
        "go_no_go": "GO_PRIMARY_OUTSIDE_CORPUS" if go else "NO_GO_SPEC_PRIMARY",
        "threshold": 10,
        "results": results,
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("n_outputs", "n_consumer_violations_labeled", "violations_caught", "over_refusals", "go_no_go")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
