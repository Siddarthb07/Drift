#!/usr/bin/env python3
"""
Coverage cost of honesty: who receives a CVD estimate vs refusal
under realistic missingness (eGFR / lipids / SBP), by race label.
"""
from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from risk_engine import compute_risk_scores  # noqa: E402

RACES = [
    "white", "aa", "south_asian", "east_asian", "hispanic",
    "middle_eastern", "indigenous", "multiracial", None,
]
DAILY = [
    {
        "sleep": 7, "steps": 8500, "stress_level": 4, "active_minutes": 30,
        "veg_servings": 3, "fruit_servings": 2, "red_meat_servings": 1, "processed_meat": 0,
    }
] * 14


def sample_user(rng: random.Random, race, miss):
    age = rng.randint(30, 75)
    sex = rng.choice(["male", "female"])
    u = {
        "age": age,
        "sex": sex,
        "sex_for_equation": sex,
        "height": 170,
        "weight": rng.uniform(55, 100),
        "waist_cm": rng.uniform(70, 110),
        "systolic": None if miss == "sbp" else rng.randint(105, 155),
        "race": race,
        "smoking_status": rng.choice(["never", "never", "ex", "current"]),
        "bp_medication": rng.choice([0, 0, 1]),
        "existing_diabetes": rng.choice([0, 0, 0, 1]),
        "high_glucose_history": 0,
        "family_history_diabetes": 0,
        "family_history_cancer": 0,
        "alcohol_per_week": rng.randint(0, 10),
        "region": "global",
    }
    labs = {}
    if miss != "lipids":
        labs["total_cholesterol"] = rng.randint(160, 260)
        labs["hdl_cholesterol"] = rng.randint(35, 70)
    if miss != "egfr":
        labs["egfr"] = rng.randint(55, 110)
    return u, labs


def main():
    rng = random.Random(42)
    n_per = 8
    missingness = ["complete", "egfr", "lipids", "sbp"]
    rows = []
    coverage = defaultdict(lambda: {"show": 0, "refuse": 0})

    for race in RACES:
        for miss in missingness:
            for _ in range(n_per):
                u, labs = sample_user(rng, race, miss if miss != "complete" else None)
                if miss == "complete":
                    # ensure complete
                    u["systolic"] = u["systolic"] or 120
                    labs.setdefault("total_cholesterol", 200)
                    labs.setdefault("hdl_cholesterol", 50)
                    labs.setdefault("egfr", 90)
                for mode in ("honest", "baseline"):
                    risk = compute_risk_scores(u, DAILY, labs, mode=mode, username="cov")
                    cvd = risk["CVD"]
                    shown = cvd.get("risk_pct") is not None or cvd.get("risk_band_label") or (
                        cvd.get("risk_pct_exact") is not None and not cvd.get("refused")
                    )
                    # honest bands store exact separately
                    if mode == "honest" and cvd.get("risk_pct_exact") is not None and not cvd.get("refused"):
                        shown = True
                    if mode == "baseline" and cvd.get("color") == "green" and "low" in (cvd.get("risk_category") or "").lower():
                        shown = True  # green under-40 counts as a shown claim
                    key = f"{race or 'unspecified'}|{miss}|{mode}"
                    gates = (
                        "labs_cholesterol", "missing_egfr", "missing_sbp",
                        "bmi_range", "age_range", "sex_equation",
                    )
                    if shown and not cvd.get("refused") and cvd.get("gate") not in gates:
                        coverage[key]["show"] += 1
                        decision = "show"
                    else:
                        coverage[key]["refuse"] += 1
                        decision = "refuse"
                    rows.append({
                        "race": race, "miss": miss, "mode": mode, "decision": decision,
                        "gate": cvd.get("gate"), "equation": cvd.get("equation"),
                    })

    # summarize complete-profile coverage by race
    summary = {"complete_coverage": {}, "egfr_missing_honest_refuse_rate": {}}
    for race in RACES:
        rk = race or "unspecified"
        for mode in ("honest", "baseline"):
            k = f"{rk}|complete|{mode}"
            s, r = coverage[k]["show"], coverage[k]["refuse"]
            summary["complete_coverage"][f"{rk}|{mode}"] = {
                "show": s, "refuse": r, "show_rate": s / (s + r) if (s + r) else 0,
            }
        ek = f"{rk}|egfr|honest"
        s, r = coverage[ek]["show"], coverage[ek]["refuse"]
        summary["egfr_missing_honest_refuse_rate"][rk] = r / (s + r) if (s + r) else 0

    out = {
        "n_rows": len(rows),
        "n_per_cell": n_per,
        "summary": summary,
        "note": (
            "Honest mode refuses CVD without eGFR — a coverage cost. "
            "Baseline may still show green under-40 claims without labs."
        ),
    }
    path = ROOT / "docs" / "facct" / "coverage_audit.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print("Wrote", path)


if __name__ == "__main__":
    main()
