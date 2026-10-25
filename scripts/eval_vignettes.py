#!/usr/bin/env python3
"""
Shared-key honesty eval with:
  - per-key rates + Wilson CIs
  - Δ excluding cancer-RR / health-age (strawman check)
  - mutation tests: inject failures into honest path and assert scorer catches them
  - balanced fixture set (study vignettes + stratified grid)
"""
from __future__ import annotations

import json
import math
import sys
from copy import deepcopy
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
    "no_green_under40",
    "no_silent_waist",
    "no_silent_sbp",
    "no_cancer_rr_hero",
    "no_health_age_hero",
    "shows_estimate_when_complete",
)

# Keys that are not hard-wired always-on in legacy (fairer Δ)
CORE_KEYS = (
    "no_white_pce_fallback",
    "no_green_under40",
    "no_silent_waist",
    "no_silent_sbp",
    "shows_estimate_when_complete",
)


def wilson_ci(successes: float, n: int, z: float = 1.96):
    if n <= 0:
        return (float("nan"), float("nan"))
    p = successes / n
    denom = 1 + z ** 2 / n
    centre = p + z ** 2 / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2))
    return ((centre - margin) / denom, (centre + margin) / denom)


def honesty_vector(vid: str, risk: dict, complete: bool, user: dict) -> dict:
    cvd, canc, diab = risk.get("CVD") or {}, risk.get("Cancer") or {}, risk.get("Diabetes") or {}
    ha = risk.get("_health_age") or {}
    race_fallback = bool(cvd.get("legacy_white_fallback"))
    cat = str(cvd.get("risk_category") or "")
    under40_green = "Under 40" in cat or (
        "low absolute risk" in cat.lower() and (user.get("age") or 99) < 40
    )
    silent_waist = bool(diab.get("silent_waist_default"))
    # SBP silent default: baseline only marks via reconstructed path; detect via flag or heuristic
    silent_sbp = bool(cvd.get("silent_sbp_default")) or bool(risk.get("_silent_sbp_default"))
    shown = (
        cvd.get("risk_pct") is not None
        or cvd.get("risk_band_label")
        or cvd.get("risk_pct_exact") is not None
    ) and not cvd.get("refused") and cvd.get("gate") not in (
        "labs_cholesterol", "missing_egfr", "missing_sbp", "age_range", "bmi_range", "sex_equation"
    )
    return {
        "no_white_pce_fallback": not race_fallback,
        "no_green_under40": not under40_green,
        "no_silent_waist": not silent_waist,
        "no_silent_sbp": not silent_sbp,
        "no_cancer_rr_hero": canc.get("relative_risk") is None,
        "no_health_age_hero": not bool(ha.get("health_age")),
        "shows_estimate_when_complete": (shown if complete else True),
    }


def load_cases():
    vigs = json.loads((ROOT / "study" / "vignettes.json").read_text())["vignettes"]
    cases = []
    for v in vigs:
        labs = v.get("labs") or {}
        complete = bool(
            labs.get("total_cholesterol") and labs.get("hdl_cholesterol") and labs.get("egfr")
            and v["user"].get("systolic")
        )
        if v["id"] in ("v3_under30", "v5_missing_chol", "v4_missing_waist"):
            if v["id"] != "v4_missing_waist":
                complete = False
        cases.append({"id": v["id"], "user": v["user"], "labs": labs, "complete": complete})

    # Stratified grid: 1 complete adult per race×sex (not 10 inflating fallback)
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
    # Explicit missing-SBP case
    cases.append({
        "id": "miss_sbp_south_asian",
        "complete": False,
        "user": {
            "age": 52, "sex": "female", "sex_for_equation": "female", "height": 162, "weight": 68,
            "waist_cm": 84, "systolic": None, "race": "south_asian", "smoking_status": "never",
            "bp_medication": 0, "existing_diabetes": 0, "high_glucose_history": 0,
            "family_history_diabetes": 0, "family_history_cancer": 0, "alcohol_per_week": 1,
        },
        "labs": {"total_cholesterol": 210, "hdl_cholesterol": 50, "egfr": 90},
    })
    return cases


def mutation_tests() -> dict:
    """Inject each known failure into an honest response dict; scorer must fail that key."""
    base_user = {
        "age": 50, "sex": "female", "sex_for_equation": "female", "height": 165, "weight": 70,
        "waist_cm": 80, "systolic": 120, "race": "south_asian", "smoking_status": "never",
        "bp_medication": 0, "existing_diabetes": 0, "high_glucose_history": 0,
        "family_history_diabetes": 0, "family_history_cancer": 0, "alcohol_per_week": 0,
    }
    honest = compute_risk_scores(
        base_user, DAILY,
        {"total_cholesterol": 200, "hdl_cholesterol": 55, "egfr": 90},
        mode="honest",
    )
    results = {}
    mutations = {
        "no_white_pce_fallback": lambda r: _mut(r, "CVD", "legacy_white_fallback", True),
        "no_green_under40": lambda r: _mut(r, "CVD", "risk_category", "Under 40 — low absolute risk"),
        "no_silent_waist": lambda r: _mut(r, "Diabetes", "silent_waist_default", True),
        "no_silent_sbp": lambda r: _mut(r, "CVD", "silent_sbp_default", True),
        "no_cancer_rr_hero": lambda r: _mut(r, "Cancer", "relative_risk", 2.1),
        "no_health_age_hero": lambda r: r.__setitem__("_health_age", {"health_age": 55.0}),
    }
    for key, mut in mutations.items():
        r = deepcopy(honest)
        if "Diabetes" not in r:
            r["Diabetes"] = {}
        if "Cancer" not in r:
            r["Cancer"] = {}
        if "CVD" not in r:
            r["CVD"] = {}
        mut(r)
        vec = honesty_vector("mut", r, True, base_user)
        results[key] = {"caught": vec[key] is False, "vector_value": vec[key]}
    results["all_caught"] = all(v["caught"] for v in results.values() if isinstance(v, dict) and "caught" in v)
    return results


def _mut(risk, section, key, value):
    risk.setdefault(section, {})
    risk[section][key] = value


def main() -> int:
    cases = load_cases()
    rows = []
    per_key = {k: {"honest": [], "baseline": []} for k in KEYS}

    for c in cases:
        for mode in ("honest", "baseline"):
            risk = compute_risk_scores(c["user"], DAILY, c["labs"], mode=mode)
            vec = honesty_vector(c["id"], risk, c["complete"], c["user"])
            for k in KEYS:
                per_key[k][mode].append(1.0 if vec[k] else 0.0)
            rows.append({
                "id": c["id"], "mode": mode, "checks": vec,
                "pass_rate": sum(vec[k] for k in KEYS) / len(KEYS),
                "core_pass_rate": sum(vec[k] for k in CORE_KEYS) / len(CORE_KEYS),
                "all_pass": all(vec[k] for k in KEYS),
            })

    def mean(mode, field="pass_rate"):
        rs = [r for r in rows if r["mode"] == mode]
        return sum(r[field] for r in rs) / len(rs)

    key_table = {}
    for k in KEYS:
        h = per_key[k]["honest"]
        b = per_key[k]["baseline"]
        key_table[k] = {
            "honest": sum(h) / len(h),
            "baseline": sum(b) / len(b),
            "n": len(h),
            "honest_wilson_95": wilson_ci(sum(h), len(h)),
            "baseline_wilson_95": wilson_ci(sum(b), len(b)),
            "delta": (sum(h) / len(h)) - (sum(b) / len(b)),
        }

    mut = mutation_tests()
    summary = {
        "n_cases": len(cases),
        "keys": list(KEYS),
        "core_keys": list(CORE_KEYS),
        "per_key": key_table,
        "honest_mean_pass_rate": mean("honest"),
        "baseline_mean_pass_rate": mean("baseline"),
        "delta_honest_minus_baseline": mean("honest") - mean("baseline"),
        "core_honest_mean": mean("honest", "core_pass_rate"),
        "core_baseline_mean": mean("baseline", "core_pass_rate"),
        "core_delta": mean("honest", "core_pass_rate") - mean("baseline", "core_pass_rate"),
        "honest_all_pass": all(r["all_pass"] for r in rows if r["mode"] == "honest"),
        "mutation_tests": mut,
        "baseline_git_pin": "a8dcc33 (pre-fix silent waist/SBP/under-40/health-age in app_v5.py)",
        "rows": rows,
    }
    out = ROOT / "docs" / "facct" / "vignette_eval.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in summary if k != "rows"}, indent=2))
    ok = (
        summary["honest_mean_pass_rate"] >= 0.95
        and summary["delta_honest_minus_baseline"] > 0.10
        and mut.get("all_caught") is True
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
