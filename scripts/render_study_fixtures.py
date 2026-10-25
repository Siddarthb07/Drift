#!/usr/bin/env python3
"""Generate participant-facing study cards from the live engines (no hand-sync)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from risk_engine import compute_risk_scores  # noqa: E402

DAILY = [{
    "sleep": 7, "steps": 9000, "stress_level": 4, "active_minutes": 30,
    "veg_servings": 3, "fruit_servings": 2, "red_meat_servings": 1, "processed_meat": 0,
}] * 14


def card(mode: str, risk: dict) -> dict:
    cvd, diab, canc = risk.get("CVD") or {}, risk.get("Diabetes") or {}, risk.get("Cancer") or {}
    ha = risk.get("_health_age") or {}
    if mode == "honest":
        cvd_txt = (
            f"10-year heart risk band: {cvd.get('risk_band_label') or cvd.get('risk_category') or 'not estimated'}"
            if not cvd.get("refused") else
            f"Heart-risk % not estimated — {cvd.get('note') or cvd.get('risk_category') or 'inputs/coverage'}"
        )
        if cvd.get("risk_pct_exact") is not None and cvd.get("risk_band_label"):
            cvd_txt = f"10-year heart risk band: {cvd.get('risk_band_label')}"
        diab_txt = "Diabetes score: " + str(diab.get("risk_band_label") or diab.get("risk_category") or "n/a")
        if diab.get("refused"):
            diab_txt = "Diabetes score not estimated"
        canc_txt = "Lifestyle factors listed (no combined risk %)" if canc.get("relative_risk") is None else f"Cancer RR {canc.get('relative_risk')}"
        hero = "Habit trajectory" if risk.get("_trajectory") is not None else "Habit tracking available"
        if (risk.get("_referral") or {}).get("recommended"):
            hero = "Consider talking with a clinician soon"
        foot = (cvd.get("note") or "")[:160] or "Educational estimate only"
        # Neutral foot: strip research jargon for study display
        if "PREVENT" in str(cvd.get("equation") or cvd.get("source") or ""):
            foot = "Published equation · educational only · not a diagnosis"
        return {"cvd": cvd_txt, "diab": diab_txt, "cancer": canc_txt, "hero": hero, "foot": foot, "heroClass": "gray" if cvd.get("refused") else ""}
    # baseline — show what legacy would show, without researcher labels
    cvd_txt = cvd.get("risk_category") or ""
    if cvd.get("risk_pct") is not None:
        cvd_txt = f"10-year heart risk: {cvd['risk_pct']}%"
    diab_txt = f"Diabetes risk: {diab.get('risk_pct')}%" if diab.get("risk_pct") is not None else str(diab.get("risk_category") or "")
    canc_txt = f"Cancer relative risk: {canc.get('relative_risk')}×" if canc.get("relative_risk") is not None else "Cancer factors"
    hero = f"Health age: {ha.get('health_age')}" if ha.get("health_age") else "Summary score"
    hero_class = "green" if "Under 40" in str(cvd.get("risk_category") or "") else ""
    foot = "See on-screen disclaimer · educational tool"
    return {"cvd": cvd_txt, "diab": diab_txt, "cancer": canc_txt, "hero": hero, "foot": foot, "heroClass": hero_class}


def main():
    vigs = json.loads((ROOT / "study" / "vignettes.json").read_text())["vignettes"]
    # Keep study length: v1,v2,v3,v6
    keep = {"v1_mid_white", "v2_south_asian", "v3_under30", "v6_high_risk"}
    # tolerate shorter ids
    out = []
    for v in vigs:
        vid = v["id"]
        if keep and not any(vid.startswith(k.split("_")[0]) or vid == k or k in vid for k in ("v1", "v2", "v3", "v6")):
            continue
        if not (vid.startswith("v1") or vid.startswith("v2") or vid.startswith("v3") or vid.startswith("v6")):
            continue
        honest = compute_risk_scores(v["user"], DAILY, v.get("labs") or {}, mode="honest")
        baseline = compute_risk_scores(v["user"], DAILY, v.get("labs") or {}, mode="baseline")
        u = v["user"]
        profile = (
            f"Age {u.get('age')} · {u.get('sex_for_equation') or u.get('sex')} · "
            f"race/ethnicity: {u.get('race')} · SBP {u.get('systolic')} · labs as seeded"
        )
        out.append({
            "id": vid,
            "title": v.get("title") or vid,
            "profile": profile,
            "honest": card("honest", honest),
            "baseline": card("baseline", baseline),
            "engine_meta": {
                "honest_equation": (honest.get("CVD") or {}).get("equation"),
                "baseline_fallback": (baseline.get("CVD") or {}).get("legacy_white_fallback"),
            },
        })
    path = ROOT / "study" / "rendered_fixtures.json"
    path.write_text(json.dumps({"fixtures": out, "generated_by": "scripts/render_study_fixtures.py"}, indent=2), encoding="utf-8")
    print(json.dumps({"n": len(out), "ids": [x["id"] for x in out]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
