#!/usr/bin/env python3
"""
Disclosure-disparity audit (P10).

Runs a persona grid through the honest vs baseline engines and reports
who receives a number, band, or refusal — by race/ethnicity and missingness.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from risk_engine import compute_risk_scores  # noqa: E402

RACES = [
    "white", "aa", "south_asian", "east_asian", "hispanic",
    "middle_eastern", "indigenous", "multiracial", None,
]


def persona(race, age=48, sex="female", waist=True, sbp=True, labs=True):
    user = {
        "age": age,
        "sex": sex,
        "sex_for_equation": sex,
        "height": 165 if sex == "female" else 175,
        "weight": 72,
        "waist_cm": 88 if waist else None,
        "systolic": 130 if sbp else None,
        "race": race,
        "smoking_status": "never",
        "bp_medication": 0,
        "existing_diabetes": 0,
        "high_glucose_history": 0,
        "family_history_diabetes": 1,
        "family_history_cancer": 0,
        "alcohol_per_week": 2,
        "region": "global",
    }
    daily = [
        {
            "sleep": 7, "steps": 9000, "stress_level": 4, "active_minutes": 35,
            "veg_servings": 3, "fruit_servings": 2, "red_meat_servings": 1, "processed_meat": 0,
        }
        for _ in range(14)
    ]
    lab = {"total_cholesterol": 205, "hdl_cholesterol": 52, "egfr": 92} if labs else {}
    return user, daily, lab


def classify(cvd: dict) -> str:
    if cvd.get("refused") or cvd.get("gate"):
        return "refuse"
    if cvd.get("risk_band_label"):
        return "band"
    if cvd.get("risk_pct") is not None:
        return "number"
    return "other"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/facct/audit_results.json")
    args = ap.parse_args()

    summary = {"honest": defaultdict(lambda: defaultdict(int)),
               "baseline": defaultdict(lambda: defaultdict(int))}
    rows = []

    for race in RACES:
        for mode in ("honest", "baseline"):
            for missing in ("complete", "no_waist", "no_sbp", "no_labs", "age_28"):
                age = 28 if missing == "age_28" else 48
                user, daily, lab = persona(
                    race,
                    age=age,
                    waist=missing != "no_waist",
                    sbp=missing != "no_sbp",
                    labs=missing != "no_labs",
                )
                risk = compute_risk_scores(user, daily, lab, mode=mode, username="audit")
                decision = classify(risk["CVD"])
                key = f"{race or 'unspecified'}|{missing}"
                summary[mode][key][decision] += 1
                rows.append({
                    "mode": mode,
                    "race": race,
                    "missing": missing,
                    "cvd_decision": decision,
                    "equation": risk["CVD"].get("equation"),
                    "claim_id": risk["CVD"].get("claim_id"),
                    "gate": risk["CVD"].get("gate"),
                    "diabetes_gate": risk["Diabetes"].get("gate"),
                    "cancer_rr": risk["Cancer"].get("relative_risk"),
                })

    # Headline: South Asian never gets White PCE number in honest mode
    sa = [r for r in rows if r["race"] == "south_asian" and r["mode"] == "honest" and r["missing"] == "complete"]
    assert all(r["equation"] != "PCE" for r in sa), "South Asian must not receive PCE"

    out = {
        "n_rows": len(rows),
        "rows": rows,
        "notes": [
            "Honest mode defaults to race-free PREVENT for all races.",
            "Unsupported PCE race never silently maps to White.",
            "Missing SBP → CVD refuse; missing waist → FINDRISC interval.",
            "Under-30 → refuse (not green 'low risk').",
        ],
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote {args.out} ({len(rows)} persona evaluations)")
    # Compact table
    for mode in ("honest", "baseline"):
        refuse = sum(1 for r in rows if r["mode"] == mode and r["cvd_decision"] == "refuse")
        show = sum(1 for r in rows if r["mode"] == mode and r["cvd_decision"] in ("band", "number"))
        print(f"  {mode}: show={show} refuse={refuse}")


if __name__ == "__main__":
    main()
