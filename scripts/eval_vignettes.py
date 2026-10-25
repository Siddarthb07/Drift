#!/usr/bin/env python3
"""Shared-key honesty eval + per-key breakdown + expanded synthetic grid."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from risk_engine import compute_risk_scores  # noqa: E402

DAILY = [
    {
        "sleep": 7, "steps": 9000, "stress_level": 4, "active_minutes": 30,
        "veg_servings": 3, "fruit_servings": 2, "red_meat_servings": 1, "processed_meat": 0,
    }
] * 14

KEYS = (
    "no_white_pce_fallback",
    "no_green_under30",
    "no_silent_waist",
    "no_cancer_rr_hero",
    "no_health_age_hero",
    "shows_estimate_when_complete",  # coverage: honest must still serve when inputs OK
)


def honesty_vector(vid: str, risk: dict, complete: bool) -> dict:
    cvd, canc, diab = risk.get("CVD") or {}, risk.get("Cancer") or {}, risk.get("Diabetes") or {}
    ha = risk.get("_health_age") or {}
    race_fallback = bool(cvd.get("legacy_white_fallback"))
    cat = cvd.get("risk_category") or ""
    under30_green = "Under 40" in cat or "low absolute risk" in cat.lower()
    silent_waist = bool(diab.get("silent_waist_default"))
    shown = (
        cvd.get("risk_pct") is not None
        or cvd.get("risk_band_label")
        or cvd.get("risk_pct_exact") is not None
    ) and not cvd.get("refused") and cvd.get("gate") not in (
        "labs_cholesterol", "missing_egfr", "missing_sbp", "age_range", "bmi_range", "sex_equation"
    )
    return {
        "no_white_pce_fallback": not race_fallback,
        "no_green_under30": not under30_green,
        "no_silent_waist": not silent_waist,
        "no_cancer_rr_hero": canc.get("relative_risk") is None,
        "no_health_age_hero": not bool(ha.get("health_age")),
        "shows_estimate_when_complete": (shown if complete else True),
    }


def load_cases():
    vigs = json.loads((ROOT / "study" / "vignettes.json").read_text())["vignettes"]
    cases = []
    for v in vigs:
        labs = v.get("labs") or {}
        complete = bool(labs.get("total_cholesterol") and labs.get("hdl_cholesterol") and labs.get("egfr"))
        if v["id"] == "v3_under30":
            complete = False  # age refuse expected in honest
        if v["id"] == "v5_missing_chol":
            complete = False
        cases.append({"id": v["id"], "user": v["user"], "labs": labs, "complete": complete})

    # Expanded grid: complete adults across races (honest should show)
    for race in ["white", "aa", "south_asian", "hispanic", "east_asian"]:
        for sex in ["female", "male"]:
            cases.append({
                "id": f"grid_{race}_{sex}",
                "complete": True,
                "user": {
                    "age": 50, "sex": sex, "sex_for_equation": sex, "height": 168, "weight": 72,
                    "waist_cm": 86, "systolic": 128, "race": race, "smoking_status": "never",
                    "bp_medication": 0, "existing_diabetes": 0, "high_glucose_history": 0,
                    "family_history_diabetes": 0, "family_history_cancer": 0, "alcohol_per_week": 2,
                },
                "labs": {"total_cholesterol": 205, "hdl_cholesterol": 52, "egfr": 92},
            })
    return cases


def main() -> int:
    cases = load_cases()
    rows = []
    per_key = {k: {"honest": [], "baseline": []} for k in KEYS}

    for c in cases:
        for mode in ("honest", "baseline"):
            risk = compute_risk_scores(c["user"], DAILY, c["labs"], mode=mode)
            vec = honesty_vector(c["id"], risk, c["complete"])
            for k in KEYS:
                per_key[k][mode].append(1.0 if vec[k] else 0.0)
            rows.append({
                "id": c["id"], "mode": mode, "checks": vec,
                "pass_rate": sum(vec[k] for k in KEYS) / len(KEYS),
                "all_pass": all(vec[k] for k in KEYS),
            })

    def mean(mode):
        rs = [r for r in rows if r["mode"] == mode]
        return sum(r["pass_rate"] for r in rs) / len(rs)

    key_table = {
        k: {
            "honest": sum(per_key[k]["honest"]) / len(per_key[k]["honest"]),
            "baseline": sum(per_key[k]["baseline"]) / len(per_key[k]["baseline"]),
        }
        for k in KEYS
    }

    summary = {
        "n_cases": len(cases),
        "keys": list(KEYS),
        "per_key": key_table,
        "honest_mean_pass_rate": mean("honest"),
        "baseline_mean_pass_rate": mean("baseline"),
        "delta_honest_minus_baseline": mean("honest") - mean("baseline"),
        "honest_all_pass": all(r["all_pass"] for r in rows if r["mode"] == "honest"),
        "rows": rows,
    }
    out = ROOT / "docs" / "facct" / "vignette_eval.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in summary if k != "rows"}, indent=2))
    # Honest should pass; delta should be > 0
    ok = summary["honest_mean_pass_rate"] >= 0.95 and summary["delta_honest_minus_baseline"] > 0.15
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
