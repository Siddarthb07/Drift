#!/usr/bin/env python3
"""Score held-out adversarial fixtures against honesty expectations (post-ledger freeze)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from risk_engine import compute_risk_scores  # noqa: E402

DAILY = [
    {
        "sleep": 7,
        "steps": 9000,
        "stress_level": 4,
        "active_minutes": 30,
        "veg_servings": 3,
        "fruit_servings": 2,
        "red_meat_servings": 1,
        "processed_meat": 0,
    }
] * 14


def _shown(cvd: dict) -> bool:
    if cvd.get("refused"):
        return False
    return bool(
        cvd.get("risk_band_label")
        or cvd.get("risk_pct_exact") is not None
        or cvd.get("risk_pct") is not None
    )


def normalize(profile: dict) -> tuple[dict, dict]:
    """Map adversarial profile keys → engine user + labs."""
    user = {
        "age": profile.get("age"),
        "race": profile.get("race", "white"),
        "smoking_status": "current" if profile.get("smoker") else "never",
        "bp_medication": 1 if profile.get("on_htn_meds") else 0,
        "existing_diabetes": 1 if profile.get("diabetic") else 0,
        "high_glucose_history": 0,
        "family_history_diabetes": 0,
        "family_history_cancer": 0,
        "alcohol_per_week": 0,
        "height": profile.get("height_cm") or profile.get("height"),
        "weight": profile.get("weight_kg") or profile.get("weight"),
        "waist_cm": profile.get("waist_cm"),
        "systolic": profile.get("sbp") if "sbp" in profile else profile.get("systolic"),
        "region": profile.get("region") or "global",
    }
    if "sex" in profile:
        user["sex"] = profile["sex"]
        # Binary sex auto-fills equation sex; nonbinary / missing leaves unset.
        if profile["sex"] in ("male", "female"):
            user["sex_for_equation"] = profile["sex"]
        else:
            user["sex_for_equation"] = profile.get("sex_for_equation") or ""
    if profile.get("prefer_pce"):
        user["prefer_pce"] = True
    labs = {}
    if profile.get("total_chol") is not None:
        labs["total_cholesterol"] = profile["total_chol"]
    if profile.get("hdl") is not None:
        labs["hdl_cholesterol"] = profile["hdl"]
    if profile.get("egfr") is not None:
        labs["egfr"] = profile["egfr"]
    return user, labs


def check(case: dict, risk: dict) -> bool:
    cvd = risk.get("CVD") or {}
    diab = risk.get("Diabetes") or {}
    canc = risk.get("Cancer") or {}
    exp = case["expect_honest"]
    age = case["profile"].get("age")
    if exp in ("refuse", "refuse_or_no_sex"):
        return not _shown(cvd)
    if exp == "refuse_not_green":
        green = "Under 40" in str(cvd.get("risk_category") or "")
        if age is not None and age < 30 and green:
            return False
        return not _shown(cvd) or not green
    if exp == "show_ascvd_with_caveat":
        return _shown(cvd)
    if exp == "prevent_not_white_pce":
        if cvd.get("legacy_white_fallback"):
            return False
        eq = str(cvd.get("equation") or cvd.get("model") or cvd.get("claim_id") or "").lower()
        # Prefer PREVENT (or refuse) — never silent White PCE for unsupported race
        if "pce" in eq and "prevent" not in eq and _shown(cvd):
            return False
        return True
    if exp == "cancer_factors_only":
        # No combined RR hero; factors-only or refuse is fine.
        if canc.get("relative_risk") is not None:
            return False
        shown_as = str(canc.get("shown_as") or "")
        policy = str(canc.get("display_policy") or "")
        return (
            canc.get("refused")
            or shown_as == "factors"
            or policy == "factors_only"
            or "factor" in str(canc.get("risk_category") or "").lower()
        )
    if exp == "waist_interval":
        if diab.get("silent_waist_default"):
            return False
        if diab.get("risk_pct") is not None:
            return False
        return bool(diab.get("score_range")) or diab.get("shown_as") == "interval" or diab.get(
            "display_policy"
        ) == "interval"
    if exp == "region_note_no_invented_equation":
        note = str(cvd.get("region_note") or cvd.get("note") or "")
        eq = str(cvd.get("equation") or cvd.get("claim_id") or "").lower()
        # Must not invent SCORE2 as the computed equation; coverage note is ok.
        if "score2" in eq or eq.startswith("qrisk") or eq.startswith("who"):
            return False
        has_note = "score2" in note.lower() or "not shipped" in note.lower() or "qrisk" in note.lower()
        uses_prevent = "prevent" in eq or cvd.get("claim_id") == "prevent_ascvd"
        return bool(_shown(cvd) and uses_prevent and has_note)
    if exp == "show_pce_or_prevent_no_fallback":
        # Negative control: supported race + prefer_pce may show PCE (or PREVENT),
        # but never legacy_white_fallback.
        if cvd.get("legacy_white_fallback"):
            return False
        return _shown(cvd)
    return False


def main() -> int:
    fixtures = json.loads((ROOT / "docs" / "facct" / "adversarial_fixtures.json").read_text())
    results = []
    for case in fixtures["cases"]:
        user, labs = normalize(case["profile"])
        risk = compute_risk_scores(user, DAILY, labs, mode="honest")
        ok = check(case, risk)
        cvd = risk.get("CVD") or {}
        diab = risk.get("Diabetes") or {}
        canc = risk.get("Cancer") or {}
        results.append(
            {
                "id": case["id"],
                "ok": ok,
                "expect": case["expect_honest"],
                "mechanism": case.get("mechanism"),
                "cvd": {
                    "refused": cvd.get("refused"),
                    "pct": cvd.get("risk_pct_exact", cvd.get("risk_pct")),
                    "band": cvd.get("risk_band_label"),
                    "equation": cvd.get("equation") or cvd.get("model") or cvd.get("claim_id"),
                    "legacy_white_fallback": cvd.get("legacy_white_fallback"),
                    "region_note": (cvd.get("region_note") or "")[:120] or None,
                },
                "diabetes": {
                    "score_range": diab.get("score_range"),
                    "shown_as": diab.get("shown_as"),
                    "silent_waist_default": diab.get("silent_waist_default"),
                },
                "cancer": {
                    "relative_risk": canc.get("relative_risk"),
                    "shown_as": canc.get("shown_as"),
                    "display_policy": canc.get("display_policy"),
                },
            }
        )
    out = {
        "n": len(results),
        "pass_rate": sum(r["ok"] for r in results) / max(len(results), 1),
        "all_passed": all(r["ok"] for r in results),
        "results": results,
        "note": fixtures.get("note"),
    }
    path = ROOT / "docs" / "facct" / "adversarial_eval.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    failed = [r["id"] for r in results if not r["ok"]]
    print(
        json.dumps(
            {
                "all_passed": out["all_passed"],
                "pass_rate": out["pass_rate"],
                "n": out["n"],
                "failed": failed,
                "results": results,
            },
            indent=2,
        )
    )
    return 0 if out["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
