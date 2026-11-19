#!/usr/bin/env python3
"""Run 5: NHANES threshold robustness across cycles + cut sensitivity + refuse safety cost.

Uses available local XPT cycles; reports design-based rates where strata/PSU present.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ["STUDY_ALLOW_BASELINE"] = "1"

OUT = ROOT / "docs" / "jbhi" / "outside_corpus" / "nhanes_robustness_report.json"


def main() -> int:
    # Prefer existing threshold CI JSON + compute_fail decomposition for safety cost
    tc_path = ROOT / "docs" / "facct" / "threshold_crossing_cis.json"
    cf_path = ROOT / "docs" / "facct" / "compute_fail_decomposition.json"
    report: dict = {"cycles": {}, "sensitivity_cuts": {}, "refuse_safety_cost": None, "notes": []}

    if tc_path.exists():
        tc = json.loads(tc_path.read_text())
        o = tc.get("design_based", {}).get("overall_both_numeric", {})
        report["cycles"]["2017_Mar2020_primary"] = {
            "cross75_leg": o.get("cross75_leg"),
            "cross75_hon": o.get("cross75_hon"),
            "cross20_leg": o.get("cross20_leg"),
            "cross20_hon": o.get("cross20_hon"),
            "source": str(tc_path),
        }
        # Sensitivity: if alternative cuts already present
        report["sensitivity_cuts"]["from_primary_file"] = {
            k: o.get(k) for k in o if k.startswith("cross")
        }
    else:
        report["notes"].append("threshold_crossing_cis.json missing")

    # Additional cycles: attempt build if XPT present
    try:
        from nhanes_coverage_audit import build_frame, row_to_user, _exact_pct, stratified_taylor_rate
        from risk_engine import compute_risk_scores
        # Default build_frame is 2017-Mar2020; document that multi-cycle XPTs may be absent
        data_root = ROOT / "data" / "nhanes"
        cycles_found = []
        if data_root.exists():
            cycles_found = sorted({p.name for p in data_root.rglob("*.xpt")})
        report["local_xpt_files_n"] = len(cycles_found)
        report["notes"].append(
            "Multi-cycle recompute requires per-cycle DEMO/BPXO merges; "
            "primary design-based CIs retained from threshold_crossing_cis.json. "
            f"Found {len(cycles_found)} local XPT files."
        )
        # Safety cost of refuse: among compute_fail, weighted share with legacy PCE >= 20%
        if cf_path.exists():
            cf = json.loads(cf_path.read_text())
            report["refuse_safety_cost"] = {
                "source": str(cf_path),
                "summary_keys": list(cf.keys())[:20],
                "note": "See compute_fail decomposition; high-risk share among refusals extracted if present.",
            }
            # Try common key patterns
            for k in ("high_risk_among_refuse", "pce_ge20_among_compute_fail", "weighted_pce_ge20_given_fail"):
                if k in cf:
                    report["refuse_safety_cost"]["value"] = cf[k]
        # Live probe: sample current frame for PCE>=20 among honest-refuse / compute_fail-like
        df = build_frame()
        w_fail = w_fail_hi = 0.0
        n = 0
        daily: list = []
        for _, row in df.iterrows():
            try:
                user, labs, meta = row_to_user(row)
            except Exception:
                continue
            if meta["wt"] <= 0:
                continue
            honest = compute_risk_scores(user, daily, labs, mode="honest", username="nhanes")
            legacy = compute_risk_scores(user, daily, labs, mode="baseline", username="nhanes")
            hc = honest.get("CVD") or {}
            lc = legacy.get("CVD") or {}
            hp = _exact_pct(hc)
            lp = _exact_pct(lc)
            refused = hp is None and (hc.get("refused") or hc.get("gate") or hc.get("compute_fail"))
            if refused or hp is None:
                w_fail += meta["wt"]
                if lp is not None and lp >= 20:
                    w_fail_hi += meta["wt"]
                n += 1
        report["refuse_safety_cost_live"] = {
            "n_rows_honest_nonnumeric": n,
            "weighted_share_legacy_pce_ge20_among_honest_nonnumeric": (w_fail_hi / w_fail) if w_fail else None,
            "interpretation": "Among adults with no honest/contract numeric CVD show, weighted share whose unconstrained PCE is ≥20%.",
        }
    except Exception as e:
        report["notes"].append(f"live robustness partial: {e}")

    # Cut sensitivity on existing both-numeric domain if we can cheaply recompute from stored CIs only
    report["planned_cuts"] = [5.0, 7.5, 10.0, 20.0]
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in report if k != "cycles"}, indent=2)[:2500])
    print("cycles", list(report.get("cycles", {}).keys()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
