#!/usr/bin/env python3
"""Run 3b: Ablate disclosure gates; report which violations get through."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("STUDY_ALLOW_BASELINE", "1")

from disclosure import apply_disclosure, public_view, DisclosureError, load_claims  # noqa: E402

OUT = ROOT / "docs" / "jbhi" / "outside_corpus" / "ablation_report.json"

# Positive cases mirroring frozen corpus intent
CASES = [
    {"id": "exact_leak", "claim_id": "prevent_ascvd", "raw": {"risk_pct": 12.3, "sbp": 130, "age": 50, "audience": "consumer"}, "expect_block": True},
    {"id": "white_fallback", "claim_id": "pce_ascvd", "raw": {"risk_pct": 10.0, "sbp": 130, "age": 55, "race": "asian", "legacy_white_fallback": True, "audience": "consumer"}, "expect_block": True},
    {"id": "missing_sbp", "claim_id": "prevent_ascvd", "raw": {"risk_pct": 8.0, "age": 50, "audience": "consumer"}, "expect_block": True},
    {"id": "unknown_claim", "claim_id": "no_such_claim", "raw": {"risk_pct": 9.0, "sbp": 120, "age": 50}, "expect_block": True},
    {"id": "health_age", "claim_id": "health_age_heuristic", "raw": {"health_age": 55, "audience": "consumer"}, "expect_block": True},
    {"id": "clinician_ok", "claim_id": "prevent_ascvd", "raw": {"risk_pct": 12.3, "sbp": 130, "age": 50, "audience": "clinician"}, "expect_block": False},
]


def blocked(out: Dict[str, Any], pub: Dict[str, Any]) -> bool:
    if out.get("refused"):
        return True
    if out.get("display_policy") == "refuse":
        return True
    if pub.get("risk_pct") is None and out.get("shown_as") in ("band", "interval", "factors", "qualitative", None):
        if out.get("shown_as") == "band" or out.get("risk_pct_exact") is not None:
            return True
    if out.get("claim_id") == "health_age_heuristic" and out.get("display_policy") == "refuse":
        return True
    return bool(out.get("shown_as") == "band" and pub.get("risk_pct") is None)


def run_case(case: Dict[str, Any]) -> bool:
    try:
        out = apply_disclosure(dict(case["raw"]), mode="honest", claim_id=case["claim_id"])
        pub = public_view(out) if isinstance(out, dict) else {}
        return blocked(out, pub if isinstance(pub, dict) else {})
    except DisclosureError:
        return True


def main() -> int:
    load_claims(refresh=True)
    full = []
    for c in CASES:
        b = run_case(c)
        full.append({"id": c["id"], "blocked": b, "expect_block": c["expect_block"], "ok": b == c["expect_block"]})

    # Ablations: monkeypatch by temporarily editing behavior via env flags simulated in-process
    # We simulate ablation by post-processing: "remove public_view strip", "ignore audience", etc.
    ablations = {}

    # Ablation A: no public_view (use raw out with exacts)
    rows = []
    for c in CASES:
        try:
            out = apply_disclosure(dict(c["raw"]), mode="honest", claim_id=c["claim_id"])
            # skip public_view — exact may remain
            b = bool(out.get("refused") or out.get("display_policy") in ("refuse", "band") and out.get("risk_pct") is None)
            if out.get("display_policy") == "band" and out.get("risk_pct_exact") is not None and out.get("risk_pct") is None:
                b = True  # still banded
            # Without public_view, risk_pct_exact leaks even when banded
            leak = out.get("risk_pct_exact") is not None and not out.get("refused")
            rows.append({"id": c["id"], "blocked_logic": b, "exact_leak_without_public_view": leak})
        except DisclosureError:
            rows.append({"id": c["id"], "blocked_logic": True, "exact_leak_without_public_view": False})
    ablations["no_public_view"] = {
        "exact_leaks": sum(1 for r in rows if r["exact_leak_without_public_view"]),
        "rows": rows,
    }

    # Ablation B: force consumer policy even for clinician (recreates over-refusal)
    rows = []
    for c in CASES:
        raw = dict(c["raw"]); raw["audience"] = "consumer"
        try:
            out = apply_disclosure(raw, mode="honest", claim_id=c["claim_id"])
            pub = public_view(out)
            b = blocked(out, pub if isinstance(pub, dict) else {})
        except DisclosureError:
            b = True
        rows.append({"id": c["id"], "blocked": b})
    ablations["force_consumer_audience"] = {
        "clinician_ok_over_refused": next((r["blocked"] for r in rows if r["id"] == "clinician_ok"), None),
        "rows": rows,
    }

    report = {
        "full_system": full,
        "full_pass": all(r["ok"] for r in full),
        "ablations": ablations,
        "audience_note": "Deviation from pre-registered outside-corpus probe: audience predicate added to reduce clinician over-refusal.",
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"full_pass": report["full_pass"], "full_system": full, "ablation_leaks": ablations["no_public_view"]["exact_leaks"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
