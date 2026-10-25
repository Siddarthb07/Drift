#!/usr/bin/env python3
"""
100-patient mixed cohort: clean / show / warn-refuse.

Each patient has distinct vitals. Expectations are checked against the honest
engine — fails CI if a clean case refuses, a warn case shows a number, or a
show case is refused.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from risk_engine import compute_risk_scores  # noqa: E402

DAILY_GOOD = [
    {
        "sleep": 7.5,
        "steps": 9500,
        "stress_level": 3,
        "active_minutes": 40,
        "veg_servings": 3,
        "fruit_servings": 2,
        "red_meat_servings": 0.5,
        "processed_meat": 0,
    }
] * 14

DAILY_OK = [
    {
        "sleep": 7,
        "steps": 8000,
        "stress_level": 4,
        "active_minutes": 30,
        "veg_servings": 2,
        "fruit_servings": 1,
        "red_meat_servings": 1,
        "processed_meat": 0,
    }
] * 14

RACES = ["white", "aa", "hispanic", "south_asian", "east_asian", "multiracial"]


def _shown(cvd: dict) -> bool:
    if cvd.get("refused"):
        return False
    return bool(
        cvd.get("risk_band_label")
        or cvd.get("risk_pct_exact") is not None
        or cvd.get("risk_pct") is not None
    )


def _pct(cvd: dict) -> Optional[float]:
    v = cvd.get("risk_pct_exact")
    if v is not None:
        return float(v)
    v = cvd.get("risk_pct")
    return float(v) if v is not None else None


def base_user(rng: random.Random, **kw) -> Tuple[dict, dict]:
    sex = kw.pop("sex", rng.choice(["female", "male"]))
    height = kw.pop("height", rng.uniform(155, 185))
    weight = kw.pop("weight", rng.uniform(55, 95))
    user = {
        "age": kw.pop("age", rng.randint(35, 65)),
        "sex": sex,
        "sex_for_equation": sex,
        "height": round(height, 1),
        "weight": round(weight, 1),
        "waist_cm": kw.pop("waist_cm", round(rng.uniform(70, 100), 1)),
        "systolic": kw.pop("systolic", rng.randint(110, 145)),
        "race": kw.pop("race", rng.choice(RACES)),
        "smoking_status": kw.pop("smoking_status", "never"),
        "bp_medication": kw.pop("bp_medication", 0),
        "existing_diabetes": kw.pop("existing_diabetes", 0),
        "high_glucose_history": 0,
        "family_history_diabetes": 0,
        "family_history_cancer": 0,
        "alcohol_per_week": kw.pop("alcohol_per_week", rng.randint(0, 5)),
        "region": "global",
    }
    user.update(kw)
    labs = {
        "total_cholesterol": kw.pop("total_cholesterol", rng.randint(170, 230))
        if "total_cholesterol" not in kw
        else kw["total_cholesterol"],
        "hdl_cholesterol": kw.pop("hdl_cholesterol", rng.randint(45, 70))
        if "hdl_cholesterol" not in kw
        else kw["hdl_cholesterol"],
        "egfr": kw.pop("egfr", rng.randint(75, 110)) if "egfr" not in kw else kw["egfr"],
    }
    # Re-apply if explicitly set via labs_* in construction helpers
    return user, labs


def make_clean(rng: random.Random, i: int) -> dict:
    """Complete, low-risk: should SHOW a low band (<5%)."""
    sex = "female" if i % 2 == 0 else "male"
    user = {
        "age": 30 + (i % 8),  # 30–37
        "sex": sex,
        "sex_for_equation": sex,
        "height": 160 + (i % 20),
        "weight": 55 + (i % 12),
        "waist_cm": 72 + (i % 8),
        "systolic": 108 + (i % 10),
        "race": RACES[i % len(RACES)],
        "smoking_status": "never",
        "bp_medication": 0,
        "existing_diabetes": 0,
        "high_glucose_history": 0,
        "family_history_diabetes": 0,
        "family_history_cancer": 0,
        "alcohol_per_week": i % 3,
        "region": "global",
    }
    labs = {
        "total_cholesterol": 165 + (i % 20),
        "hdl_cholesterol": 55 + (i % 15),
        "egfr": 90 + (i % 20),
    }
    return {
        "id": f"clean_{i:03d}",
        "bucket": "clean",
        "expect": {"cvd_shown": True, "max_pct": 5.0, "gate_not": "refuse"},
        "user": user,
        "labs": labs,
        "daily": DAILY_GOOD,
    }


def make_show(rng: random.Random, i: int) -> dict:
    """Complete mid/high-risk: should SHOW a numeric (often ≥5%)."""
    sex = "male" if i % 2 == 0 else "female"
    user = {
        "age": 55 + (i % 20),  # 55–74
        "sex": sex,
        "sex_for_equation": sex,
        "height": 165 + (i % 15),
        "weight": 80 + (i % 25),
        "waist_cm": 95 + (i % 15),
        "systolic": 145 + (i % 25),
        "race": RACES[i % len(RACES)],
        "smoking_status": "current" if i % 3 != 2 else "ex",
        "bp_medication": 1 if i % 2 == 0 else 0,
        "existing_diabetes": 1 if i % 4 == 0 else 0,
        "high_glucose_history": 1 if i % 5 == 0 else 0,
        "family_history_diabetes": 1,
        "family_history_cancer": 0,
        "alcohol_per_week": 4 + (i % 6),
        "region": "global",
        "statin": 1 if i % 3 == 0 else 0,
    }
    labs = {
        "total_cholesterol": 220 + (i % 40),
        "hdl_cholesterol": 35 + (i % 12),
        "egfr": 60 + (i % 25),
    }
    return {
        "id": f"show_{i:03d}",
        "bucket": "show",
        "expect": {"cvd_shown": True, "min_pct": None},  # must show; risk level varies
        "user": user,
        "labs": labs,
        "daily": DAILY_OK,
    }


def make_warn(rng: random.Random, i: int) -> dict:
    """Should REFUSE with a known gate — no silent number."""
    patterns = [
        "missing_sbp",
        "missing_egfr",
        "labs_cholesterol",
        "age_under",
        "age_over",
        "sex_equation",
        "profile",
    ]
    kind = patterns[i % len(patterns)]
    sex = "female" if i % 2 else "male"
    user = {
        "age": 50 + (i % 15),
        "sex": sex,
        "sex_for_equation": sex,
        "height": 168.0,
        "weight": 72.0,
        "waist_cm": 85.0,
        "systolic": 130,
        "race": RACES[i % len(RACES)],
        "smoking_status": "never",
        "bp_medication": 0,
        "existing_diabetes": 0,
        "high_glucose_history": 0,
        "family_history_diabetes": 0,
        "family_history_cancer": 0,
        "alcohol_per_week": 1,
        "region": "global",
    }
    labs = {"total_cholesterol": 200, "hdl_cholesterol": 50, "egfr": 90}
    expect_gate = kind

    if kind == "missing_sbp":
        user["systolic"] = None
        expect_gate = "missing_sbp"
    elif kind == "missing_egfr":
        labs["egfr"] = None
        expect_gate = "missing_egfr"
    elif kind == "labs_cholesterol":
        if i % 2 == 0:
            labs["total_cholesterol"] = None
        else:
            labs["hdl_cholesterol"] = None
        expect_gate = "labs_cholesterol"
    elif kind == "age_under":
        user["age"] = 22 + (i % 7)  # 22–28
        expect_gate = "age_range"
    elif kind == "age_over":
        user["age"] = 80 + (i % 5)
        expect_gate = "age_range"
    elif kind == "sex_equation":
        # Clear both fields — engine falls back from sex_for_equation → sex
        user["sex"] = None
        user["sex_for_equation"] = None
        expect_gate = "sex_equation"
    elif kind == "profile":
        user["weight"] = None
        expect_gate = "profile"

    return {
        "id": f"warn_{i:03d}",
        "bucket": "warn",
        "expect": {"cvd_shown": False, "gate": expect_gate},
        "user": user,
        "labs": labs,
        "daily": DAILY_OK,
        "warn_kind": kind,
    }


def build_cohort(seed: int = 42, n: int = 100) -> List[dict]:
    rng = random.Random(seed)
    # 34 clean, 33 show, 33 warn
    n_clean, n_show, n_warn = 34, 33, 33
    assert n_clean + n_show + n_warn == n
    cases = []
    for i in range(n_clean):
        cases.append(make_clean(rng, i))
    for i in range(n_show):
        cases.append(make_show(rng, i))
    for i in range(n_warn):
        cases.append(make_warn(rng, i))
    rng.shuffle(cases)
    return cases


def evaluate_case(case: dict) -> Dict[str, Any]:
    risk = compute_risk_scores(
        case["user"], case["daily"], case["labs"], mode="honest", username=case["id"]
    )
    cvd = risk.get("CVD") or {}
    shown = _shown(cvd)
    pct = _pct(cvd)
    gate = cvd.get("gate")
    exp = case["expect"]
    ok = True
    reasons: List[str] = []

    if exp["cvd_shown"] and not shown:
        ok = False
        reasons.append(f"expected show, got refuse gate={gate}")
    if not exp["cvd_shown"] and shown:
        ok = False
        reasons.append(f"expected refuse, got pct={pct}")
    if exp.get("gate") and gate != exp["gate"]:
        # profile incomplete may refuse before CVD-specific gates
        if not (exp["gate"] == "profile" and cvd.get("refused")):
            if gate != exp["gate"]:
                ok = False
                reasons.append(f"expected gate={exp['gate']}, got {gate}")
    if shown and exp.get("max_pct") is not None and pct is not None:
        if pct > exp["max_pct"]:
            ok = False
            reasons.append(f"expected pct≤{exp['max_pct']}, got {pct}")
    if shown and case["bucket"] == "show" and pct is not None and pct < 0:
        ok = False
        reasons.append("negative risk")

    return {
        "id": case["id"],
        "bucket": case["bucket"],
        "ok": ok,
        "reasons": reasons,
        "shown": shown,
        "pct": pct,
        "band": cvd.get("risk_band_label"),
        "gate": gate,
        "refused": bool(cvd.get("refused")),
        "equation": cvd.get("equation") or cvd.get("claim_id"),
        "age": case["user"].get("age"),
        "race": case["user"].get("race"),
        "sex": case["user"].get("sex_for_equation") or case["user"].get("sex"),
    }


def run_cohort(seed: int = 42, n: int = 100) -> Dict[str, Any]:
    cases = build_cohort(seed=seed, n=n)
    results = [evaluate_case(c) for c in cases]
    by_bucket: Dict[str, List[dict]] = {"clean": [], "show": [], "warn": []}
    for r in results:
        by_bucket[r["bucket"]].append(r)

    def _summ(rows: List[dict]) -> dict:
        return {
            "n": len(rows),
            "pass": sum(1 for r in rows if r["ok"]),
            "fail": sum(1 for r in rows if not r["ok"]),
            "shown": sum(1 for r in rows if r["shown"]),
            "refused": sum(1 for r in rows if r["refused"]),
            "mean_pct_when_shown": round(
                sum(r["pct"] for r in rows if r["pct"] is not None)
                / max(1, sum(1 for r in rows if r["pct"] is not None)),
                3,
            )
            if any(r["pct"] is not None for r in rows)
            else None,
        }

    failures = [r for r in results if not r["ok"]]
    report = {
        "seed": seed,
        "n": n,
        "all_passed": len(failures) == 0,
        "pass_rate": round(sum(1 for r in results if r["ok"]) / n, 4),
        "by_bucket": {k: _summ(v) for k, v in by_bucket.items()},
        "failures": failures,
        "sample": {
            "clean": [r for r in results if r["bucket"] == "clean"][:3],
            "show": [r for r in results if r["bucket"] == "show"][:3],
            "warn": [r for r in results if r["bucket"] == "warn"][:3],
        },
        "note": (
            "clean=complete low-risk must show ≤5%; show=complete elevated must show; "
            "warn=missing/out-of-range must refuse (no silent number)."
        ),
    }
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / "docs" / "facct" / "patient_cohort_sim.json",
    )
    args = ap.parse_args()
    report = run_cohort(seed=args.seed, n=args.n)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("n", "all_passed", "pass_rate", "by_bucket", "failures")}, indent=2))
    if report["failures"]:
        print("FAILURES:", json.dumps(report["failures"], indent=2))
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
