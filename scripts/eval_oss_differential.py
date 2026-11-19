#!/usr/bin/env python3
"""Run 1: Mechanical-oracle differential testing of open-source CVD calculators.

Violation flags are decided by oracles (no human labels):
  - silent_imputation: missing SBP/lipids still returns a numeric risk
  - silent_white_fallback: asian/hispanic/other risk ≈ White PCE (±0.05 pp)
  - oor_coverage: extreme labs/ages still return a number
  - exact_precision: returns a point percent (always true for numeric libs)
  - transcription_error: |risk - Drift PCE/PREVENT golden| > 0.5 pp on AHA-like cases

Then applies Drift disclosure contracts (consumer audience) for catch / over-refusal.
"""
from __future__ import annotations

import json
import math
import os
import sys
import traceback
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OSS = ROOT / "docs" / "jbhi" / "outside_corpus" / "oss_checkout"
OUT = ROOT / "docs" / "jbhi" / "outside_corpus" / "oss_differential_report.json"

os.environ.setdefault("STUDY_ALLOW_BASELINE", "1")

from risk_calculators import pooled_cohort_cvd_10yr  # noqa: E402
from prevent_equations import prevent_10yr  # noqa: E402
from disclosure import apply_disclosure, public_view, DisclosureError  # noqa: E402


Profile = Dict[str, Any]


def _near(a: float, b: float, tol: float = 0.05) -> bool:
    return abs(float(a) - float(b)) <= tol


def drift_pce(p: Profile) -> Optional[float]:
    r = pooled_cohort_cvd_10yr(
        p["age"], p["sex"], p["tc"], p["hdl"], p["sbp"],
        p.get("bp_tx", False), p.get("smoker", False), p.get("diabetes", False),
        race=p.get("race", "white"),
    )
    return None if r is None else float(r["risk_pct"])


def drift_prevent(p: Profile) -> Optional[float]:
    try:
        r = prevent_10yr(
            sex=p["sex"], age=p["age"], total_chol=p["tc"], hdl_chol=p["hdl"],
            sbp=p["sbp"], diabetes=p.get("diabetes", False),
            current_smoker=p.get("smoker", False), bmi=p.get("bmi", 27),
            egfr=p.get("egfr", 90), bp_treated=p.get("bp_tx", False),
            statin=False, outcome="ascvd",
        )
        return None if r is None else float(r["risk_pct"])
    except Exception:
        return None


# --- Adapters (return risk_pct float or None if refuse/error) ---

def adapter_articulus(p: Profile) -> Optional[float]:
    sys.path.insert(0, str(OSS / "Articulus-Tech_ascvd"))
    import ascvd  # type: ignore
    race = p.get("race", "white")
    if race not in ("white", "aa"):
        # library may throw or coerce — try and observe
        try:
            obj = ascvd.ASCVD(
                age=p["age"], gender=p["sex"], race=race,
                total_cholesterol=p["tc"], hdl=p["hdl"], systolic=p["sbp"],
                hypertensive=p.get("bp_tx", False), smoker=p.get("smoker", False),
                diabetic=p.get("diabetes", False),
            )
            return float(obj.compute_ten_year_score())
        except Exception:
            return None
    obj = ascvd.ASCVD(
        age=p["age"], gender=p["sex"], race=race,
        total_cholesterol=p["tc"], hdl=p["hdl"], systolic=p["sbp"],
        hypertensive=p.get("bp_tx", False), smoker=p.get("smoker", False),
        diabetic=p.get("diabetes", False),
    )
    return float(obj.compute_ten_year_score())


def adapter_prevent_is(p: Profile) -> Optional[float]:
    sys.path.insert(0, str(OSS / "InterconnectedSystems_prevent-calculator"))
    import prevent_calculator as pc  # type: ignore
    try:
        res = pc.calculate_risk(
            p["age"], p["sex"], p["tc"], p["hdl"], p["sbp"],
            p.get("bp_tx", False), p.get("smoker", False), p.get("diabetes", False),
            p.get("bmi", 27), p.get("egfr", 90), False,
        )
        return float(res["ascvd_10"])
    except Exception:
        return None


def adapter_drift_pce(p: Profile) -> Optional[float]:
    return drift_pce(p)


def adapter_drift_prevent(p: Profile) -> Optional[float]:
    return drift_prevent(p)


# Dynamic discovery: Python files that look like ASCVD calculators
def adapter_abusura_pce(p: Profile) -> Optional[float]:
    """Known pattern: non-AA races coerced to White coefficients."""
    sys.path.insert(0, str(OSS / "abusuraihsakhri_ascvd-risk-calculator"))
    import ascvd_pooled_cohort as apc  # type: ignore
    try:
        r = apc.ten_year_ascvd(
            age=int(p["age"]), sex=p["sex"], race=str(p.get("race", "white")),
            total_cholesterol=float(p["tc"]), hdl=float(p["hdl"]), sbp=float(p["sbp"]),
            treated_htn=bool(p.get("bp_tx", False)), smoker=bool(p.get("smoker", False)),
            diabetes=bool(p.get("diabetes", False)),
        )
        return float(r.ten_year_risk_pct)
    except Exception:
        return None


def adapter_adoracion_framingham(p: Profile) -> Optional[float]:
    """Silently defaults HDL by sex — oracle silent_imputation when HDL missing path used."""
    sys.path.insert(0, str(OSS / "Adoracion2020_Framingham-risk-calculator"))
    import framingham10yr as fh  # type: ignore
    try:
        # API uses sex 1/0 or male/female
        sex = 1 if p["sex"] == "male" else 0
        # Function returns points table path; try to get risk if available
        pts = fh.points_framingham_10year_risk(
            sex, p["age"], p["tc"], p["sbp"], 1 if p.get("smoker") else 0,
            1 if p.get("bp_tx") else 0,
        )
        if isinstance(pts, (int, float)):
            return float(pts)
        return float(pts) if pts is not None else None
    except Exception:
        return None


def adapter_prevent_benchmark(p: Profile) -> Optional[float]:
    sys.path.insert(0, str(OSS / "maher-coder_prevent-benchmark" / "src"))
    try:
        import prevent_equations as pe  # type: ignore
    except Exception:
        return None
    try:
        # Best-effort call depending on signature
        if hasattr(pe, "prevent_10yr"):
            r = pe.prevent_10yr(
                sex=p["sex"], age=p["age"], total_chol=p["tc"], hdl_chol=p["hdl"],
                sbp=p["sbp"], diabetes=p.get("diabetes", False),
                current_smoker=p.get("smoker", False), bmi=p.get("bmi", 27),
                egfr=p.get("egfr", 90), bp_treated=p.get("bp_tx", False),
            )
            if isinstance(r, dict):
                return float(r.get("risk_pct") or r.get("ascvd") or list(r.values())[0])
            return float(r)
    except Exception:
        return None
    return None


def _try_import_callables() -> List[Tuple[str, Callable[[Profile], Optional[float]]]]:
    return [
        ("drift_pce_reference", adapter_drift_pce),
        ("drift_prevent_reference", adapter_drift_prevent),
        ("Articulus-Tech_ascvd", adapter_articulus),
        ("InterconnectedSystems_prevent-calculator", adapter_prevent_is),
        ("abusuraihsakhri_ascvd-risk-calculator", adapter_abusura_pce),
        ("maher-coder_prevent-benchmark", adapter_prevent_benchmark),
        ("Adoracion2020_Framingham-risk-calculator", adapter_adoracion_framingham),
    ]


def build_probe_grid() -> List[Profile]:
    """~fixed grid (expanded systematically; not random)."""
    grid: List[Profile] = []
    # AHA / ACC-like transcription anchors
    anchors = [
        dict(age=55, sex="female", tc=213, hdl=50, sbp=120, bp_tx=False, smoker=False, diabetes=False, race="white", tag="pce_white_f_anchor"),
        dict(age=55, sex="female", tc=213, hdl=50, sbp=120, bp_tx=False, smoker=False, diabetes=False, race="aa", tag="pce_aa_f_anchor"),
        dict(age=55, sex="male", tc=213, hdl=50, sbp=120, bp_tx=False, smoker=False, diabetes=False, race="white", tag="pce_white_m_anchor"),
        dict(age=50, sex="female", tc=200, hdl=45, sbp=160, bp_tx=True, smoker=False, diabetes=True, bmi=35, egfr=90, race="white", tag="prevent_f_anchor"),
        dict(age=55, sex="male", tc=185.6, hdl=50.3, sbp=130, bp_tx=False, smoker=False, diabetes=False, bmi=25, egfr=90, race="white", tag="prevent_m_anchor"),
    ]
    grid.extend(anchors)

    base = dict(age=55, sex="female", tc=210, hdl=50, sbp=130, bp_tx=False, smoker=False, diabetes=False, bmi=27, egfr=90)

    # Missing inputs
    for miss, val in [("sbp", None), ("tc", None), ("hdl", None)]:
        p = dict(base); p[miss] = val; p["race"] = "white"; p["tag"] = f"missing_{miss}"
        grid.append(p)

    # Race fallback probes
    for race in ["asian", "hispanic", "other", "south_asian"]:
        p = dict(base); p["race"] = race; p["tag"] = f"race_{race}"
        grid.append(p)
        # paired white for equality check
        w = dict(base); w["race"] = "white"; w["tag"] = f"race_{race}__white_pair"
        grid.append(w)

    # OOR coverage
    for tag, overrides in [
        ("oor_tc400", dict(tc=400)),
        ("oor_sbp230", dict(sbp=230)),
        ("oor_age25", dict(age=25)),
        ("oor_age85", dict(age=85)),
        ("oor_hdl10", dict(hdl=10)),
        ("oor_combo", dict(tc=400, sbp=230, age=85)),
    ]:
        p = dict(base); p.update(overrides); p["race"] = "white"; p["tag"] = tag
        grid.append(p)

    # Expand factorial grid for volume (~500)
    sexes = ["female", "male"]
    ages = [40, 50, 55, 65, 75]
    races = ["white", "aa", "asian", "hispanic", "other"]
    sbps = [110, 130, 160]
    tcs = [160, 200, 240]
    # 2*5*5*3*3 = 450
    for sex in sexes:
        for age in ages:
            for race in races:
                for sbp in sbps:
                    for tc in tcs:
                        grid.append(dict(
                            age=age, sex=sex, tc=tc, hdl=50, sbp=sbp, bp_tx=(sbp >= 140),
                            smoker=False, diabetes=False, bmi=27, egfr=90, race=race,
                            tag=f"fact_{sex}_{age}_{race}_{sbp}_{tc}",
                        ))
    return grid


@dataclass
class RepoResult:
    repo: str
    n_profiles: int
    n_numeric: int
    silent_imputation: int
    silent_white_fallback: int
    oor_coverage: int
    exact_precision: int
    transcription_error: int
    n_transcription_checked: int
    contract_caught: int
    over_refusal: int
    errors: int
    notes: List[str]


def oracle_flags(adapter_name: str, adapter: Callable, grid: List[Profile]) -> RepoResult:
    notes: List[str] = []
    silent_imp = silent_fb = oor = exact = transc_err = transc_n = 0
    numeric = errors = caught = over = 0

    # Precompute white reference for fallback pairs via same adapter when possible
    white_cache: Dict[str, Optional[float]] = {}

    for p in grid:
        tag = p.get("tag", "")
        # Build call profile with missing fields omitted / None
        call = {k: v for k, v in p.items() if k != "tag"}
        try:
            # Missing-input probes: pass None and see if numeric returns
            if tag.startswith("missing_"):
                field = tag.split("_", 1)[1]
                call[field] = None
                # Some adapters need int — simulate "caller forgot field" by deleting
                call.pop(field, None)
                # Also try with a silent default the app might use
                call2 = dict(p); call2.pop("tag", None)
                if field == "sbp":
                    call2["sbp"] = 120  # common silent default — we still test missing path first
                try:
                    r_miss = adapter(call)
                except Exception:
                    r_miss = None
                if r_miss is not None and not (isinstance(r_miss, float) and math.isnan(r_miss)):
                    silent_imp += 1
                    numeric += 1
                    exact += 1
                continue

            r = adapter(call)
        except Exception as e:
            errors += 1
            if len(notes) < 5:
                notes.append(f"{tag}: {type(e).__name__}: {e}")
            continue

        if r is None:
            continue
        try:
            rv = float(r)
        except Exception:
            errors += 1
            continue
        if math.isnan(rv):
            continue
        numeric += 1
        exact += 1  # libraries returning a float are exact-precision displays by oracle

        if tag.startswith("oor_"):
            oor += 1

        # White fallback oracle: race_* vs white pair — only for race-stratified PCE-like adapters.
        # Race-free PREVENT equality is expected and must NOT count as silent fallback.
        if tag.startswith("race_") and not tag.endswith("__white_pair"):
            race = p["race"]
            is_prevent_like = "prevent" in adapter_name.lower()
            if (not is_prevent_like) and race not in ("white", "aa"):
                wp = dict(call); wp["race"] = "white"
                try:
                    wr = adapter(wp)
                except Exception:
                    wr = None
                if wr is not None and _near(rv, float(wr), 0.05):
                    silent_fb += 1

        # Transcription vs Drift goldens on anchors
        if tag.endswith("_anchor") or tag in (
            "pce_white_f_anchor", "pce_aa_f_anchor", "pce_white_m_anchor",
            "prevent_f_anchor", "prevent_m_anchor",
        ):
            if "prevent" in tag:
                gold = drift_prevent(p)
            else:
                gold = drift_pce(p)
            if gold is not None:
                transc_n += 1
                if abs(rv - gold) > 0.5:
                    transc_err += 1

        # Contract probe (consumer): map to payload
        claim = "prevent_ascvd" if "prevent" in adapter_name.lower() or "prevent" in tag else "pce_ascvd"
        raw = {
            "risk_pct": rv, "sbp": call.get("sbp") or 130, "age": call.get("age") or 55,
            "race": call.get("race") or "white", "legacy_white_fallback": False,
            "audience": "consumer",
        }
        if call.get("race") not in ("white", "aa", None) and claim == "pce_ascvd":
            # if adapter returned a number for unsupported race, mark fallback for contract
            raw["legacy_white_fallback"] = True
            raw["race"] = call.get("race")
        try:
            out = apply_disclosure(raw, mode="honest", claim_id=claim)
            pub = public_view(out)
            blocked = bool(out.get("refused") or pub.get("risk_pct") is None)
            # consumer exact percent is a violation the contract should catch via banding
            if blocked:
                caught += 1
            else:
                # leaked exact — contract miss
                pass
            # over-refusal: clinician-intended exact on white/aa in-range — counted separately in post
        except DisclosureError:
            caught += 1

    # Over-refusal estimate: in-range white/aa anchors blocked under consumer policy
    # (reported; Run 3 introduces audience=clinician to fix)
    for p in grid:
        if not str(p.get("tag", "")).endswith("_anchor"):
            continue
        if p.get("race") not in ("white", "aa"):
            continue
        try:
            r = adapter({k: v for k, v in p.items() if k != "tag"})
        except Exception:
            continue
        if r is None:
            continue
        claim = "pce_ascvd"
        raw = {"risk_pct": float(r), "sbp": p["sbp"], "age": p["age"], "race": p["race"], "audience": "clinician"}
        try:
            out = apply_disclosure(raw, mode="honest", claim_id=claim)
            # if still refuses/bands clinician, count over-refusal after Run3 fix should drop
            if out.get("refused") or out.get("risk_pct") is None and out.get("display_policy") == "band":
                # band strips risk_pct — for clinician audience we will allow number
                if out.get("shown_as") == "band" or out.get("risk_pct") is None:
                    over += 1
        except DisclosureError:
            over += 1

    return RepoResult(
        repo=adapter_name, n_profiles=len(grid), n_numeric=numeric,
        silent_imputation=silent_imp, silent_white_fallback=silent_fb,
        oor_coverage=oor, exact_precision=exact,
        transcription_error=transc_err, n_transcription_checked=transc_n,
        contract_caught=caught, over_refusal=over, errors=errors, notes=notes,
    )


def main() -> int:
    grid = build_probe_grid()
    adapters = _try_import_callables()
    results = []
    for name, fn in adapters:
        try:
            results.append(asdict(oracle_flags(name, fn, grid)))
            print("ok", name, results[-1]["silent_white_fallback"], results[-1]["transcription_error"])
        except Exception as e:
            results.append({"repo": name, "fatal": str(e), "trace": traceback.format_exc()[:500]})
            print("fail", name, e)

    # Summary oracles across non-reference adapters
    external = [r for r in results if isinstance(r.get("silent_white_fallback"), int) and not r["repo"].startswith("drift_")]
    summary = {
        "n_grid_profiles": len(grid),
        "n_adapters": len(results),
        "n_external_adapters": len(external),
        "external_any_silent_white_fallback": sum(1 for r in external if r["silent_white_fallback"] > 0),
        "external_any_silent_imputation": sum(1 for r in external if r["silent_imputation"] > 0),
        "external_any_oor_coverage": sum(1 for r in external if r["oor_coverage"] > 0),
        "external_transcription_errors_total": sum(r["transcription_error"] for r in external),
        "external_transcription_checked_total": sum(r["n_transcription_checked"] for r in external),
        "repos_cloned": len(list(OSS.iterdir())) if OSS.exists() else 0,
        "results": results,
        "oracle_definitions": {
            "silent_imputation": "missing SBP/TC/HDL still returns numeric",
            "silent_white_fallback": "asian/hispanic/other/south_asian risk within 0.05pp of White on same labs",
            "oor_coverage": "numeric returned on extreme age/labs",
            "transcription_error": "|adapter - Drift golden| > 0.5pp on anchors",
        },
    }
    OUT.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in summary if k != "results"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
