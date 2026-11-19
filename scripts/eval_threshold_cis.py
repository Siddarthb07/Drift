#!/usr/bin/env python3
"""Design-based CIs for PCE–PREVENT threshold crossings (overall + strata)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

os.environ["STUDY_ALLOW_BASELINE"] = "1"

from nhanes_coverage_audit import (  # noqa: E402
    _exact_pct,
    build_frame,
    row_to_user,
    stratified_taylor_rate,
)
from risk_engine import compute_risk_scores  # noqa: E402


def main() -> int:
    df = build_frame()
    design_recs = []
    daily: list = []
    for _, row in df.iterrows():
        try:
            user, labs, meta = row_to_user(row)
        except Exception:
            continue
        if meta["wt"] <= 0 or meta["strata"] is None or meta["psu"] is None:
            continue
        honest = compute_risk_scores(user, daily, labs, mode="honest", username="nhanes")
        legacy = compute_risk_scores(user, daily, labs, mode="baseline", username="nhanes")
        hc = honest.get("CVD") or {}
        lc = legacy.get("CVD") or {}
        hp = _exact_pct(hc)
        lp = _exact_pct(lc)
        both = hp is not None and lp is not None
        fallback = bool(lc.get("legacy_white_fallback"))
        race = meta["race"]
        nofb = both and (not fallback) and race in ("white", "aa")
        fb = both and fallback
        design_recs.append(
            {
                "wt": meta["wt"],
                "strata": meta["strata"],
                "psu": meta["psu"],
                "both_numeric": both,
                "in_nofb": nofb,
                "in_fb": fb,
                "cross75_leg": bool(both and hp < 7.5 <= lp),
                "cross75_hon": bool(both and lp < 7.5 <= hp),
                "cross20_leg": bool(both and hp < 20.0 <= lp),
                "cross20_hon": bool(both and lp < 20.0 <= hp),
            }
        )

    def block(y_key: str, domain: str) -> dict:
        out = stratified_taylor_rate(design_recs, y_key, domain_key=domain)
        return {
            "estimate": out.get("estimate"),
            "se": out.get("se"),
            "ci95": out.get("ci95"),
            "df": out.get("df"),
            "n_domain": out.get("n_domain"),
            "ci_bound_note": (
                "Student-t interval truncated to [0,1] "
                "(lo=max(0,R-t*SE), hi=min(1,R+t*SE)); lower bound may hit 0"
            ),
        }

    payload = {
        "n_analyzed": len(design_recs),
        "n_both_numeric": sum(1 for r in design_recs if r["both_numeric"]),
        "n_nofb_both_numeric": sum(1 for r in design_recs if r["in_nofb"]),
        "n_fb_both_numeric": sum(1 for r in design_recs if r["in_fb"]),
        "design_based": {
            "overall_both_numeric": {
                "cross75_leg": block("cross75_leg", "both_numeric"),
                "cross75_hon": block("cross75_hon", "both_numeric"),
                "cross20_leg": block("cross20_leg", "both_numeric"),
                "cross20_hon": block("cross20_hon", "both_numeric"),
            },
            "no_fallback_stratum": {
                "cross75_leg": block("cross75_leg", "in_nofb"),
                "cross75_hon": block("cross75_hon", "in_nofb"),
                "cross20_leg": block("cross20_leg", "in_nofb"),
                "cross20_hon": block("cross20_hon", "in_nofb"),
            },
            "fallback_stratum": {
                "cross75_leg": block("cross75_leg", "in_fb"),
                "cross75_hon": block("cross75_hon", "in_fb"),
                "cross20_leg": block("cross20_leg", "in_fb"),
                "cross20_hon": block("cross20_hon", "in_fb"),
            },
        },
        "descriptive_contrast_note": (
            "nofb vs fallback is a descriptive contrast of design-based prevalences; "
            "no formal hypothesis test is claimed."
        ),
        "interpretation": (
            "Primary: design-based weighted prevalence among both-numeric adults. "
            "Stratum CIs support the equation-shift (not remapping-only) argument."
        ),
    }
    path = ROOT / "docs" / "facct" / "threshold_crossing_cis.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        json.dumps(
            {
                "path": str(path.relative_to(ROOT)),
                "n_both": payload["n_both_numeric"],
                "overall75": payload["design_based"]["overall_both_numeric"]["cross75_leg"],
                "nofb75": payload["design_based"]["no_fallback_stratum"]["cross75_leg"],
                "fb75": payload["design_based"]["fallback_stratum"]["cross75_leg"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
