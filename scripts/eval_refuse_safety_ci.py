#!/usr/bin/env python3
"""D3: Design-based CI for refuse-safety share (unconstrained PCE ≥20% among contract non-numeric)."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

OUT = ROOT / "docs" / "jbhi" / "outside_corpus" / "refuse_safety_ci.json"


def main() -> int:
    from nhanes_coverage_audit import build_frame, row_to_user, _exact_pct, stratified_taylor_rate
    from risk_engine import compute_risk_scores

    df = build_frame()
    daily: list = []
    records = []
    by_reason = {"compute_fail": 0.0, "refused_other": 0.0, "missing_numeric": 0.0, "w_total": 0.0}
    n = 0
    for _, row in df.iterrows():
        try:
            user, labs, meta = row_to_user(row)
        except Exception:
            continue
        wt = float(meta.get("wt") or 0.0)
        if wt <= 0:
            continue
        honest = compute_risk_scores(user, daily, labs, mode="honest", username="nhanes")
        legacy = compute_risk_scores(user, daily, labs, mode="baseline", username="nhanes")
        hc = honest.get("CVD") or {}
        lc = legacy.get("CVD") or {}
        hp = _exact_pct(hc)
        lp = _exact_pct(lc)
        nonnumeric = hp is None
        if not nonnumeric:
            continue
        n += 1
        y = 1.0 if (lp is not None and lp >= 20.0) else 0.0
        records.append({
            "wt": wt,
            "strata": meta.get("strata") or meta.get("SDMVSTRA"),
            "psu": meta.get("psu") or meta.get("SDMVPSU"),
            "y_ge20": y,
            "in_domain": True,
        })
        by_reason["w_total"] += wt
        gate = str(hc.get("gate") or "")
        if hc.get("compute_fail") or gate == "compute_fail":
            by_reason["compute_fail"] += wt
        elif hc.get("refused"):
            by_reason["refused_other"] += wt
        else:
            by_reason["missing_numeric"] += wt

    # Ensure strata/psu ints where possible
    cleaned = []
    for r in records:
        try:
            cleaned.append({
                **r,
                "strata": int(r["strata"]) if r["strata"] is not None else None,
                "psu": int(r["psu"]) if r["psu"] is not None else None,
            })
        except Exception:
            continue

    taylor = stratified_taylor_rate(cleaned, "y_ge20", domain_key="in_domain")
    # Also Wilson on unweighted for transparency
    k = int(sum(r["y_ge20"] for r in cleaned))
    n_u = len(cleaned)
    z = 1.96
    if n_u:
        den = 1 + z * z / n_u
        p = k / n_u
        center = (p + z * z / (2 * n_u)) / den
        half = (z / den) * math.sqrt(p * (1 - p) / n_u + z * z / (4 * n_u * n_u))
        wilson = [max(0, center - half), min(1, center + half)]
    else:
        wilson = [0.0, 0.0]

    wtot = by_reason["w_total"] or 1.0
    report = {
        "weighted_share": taylor.get("estimate"),
        "design_based": taylor,
        "n_contract_nonnumeric": n_u,
        "approx_unweighted_k": k,
        "wilson95_unweighted_approx": wilson,
        "by_refusal_reason_weighted_share": {
            "compute_fail": by_reason["compute_fail"] / wtot,
            "refused_other": by_reason["refused_other"] / wtot,
            "missing_numeric": by_reason["missing_numeric"] / wtot,
        },
        "note": "Design-based stratified Taylor CI among adults with no contract/honest CVD numeric; y=1 if unconstrained PCE ≥20%.",
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "weighted_share": report["weighted_share"],
        "ci95": taylor.get("ci95"),
        "n": n_u,
        "by_reason": report["by_refusal_reason_weighted_share"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
