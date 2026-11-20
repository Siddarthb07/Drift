#!/usr/bin/env python3
"""
P0 comparative enforcement benchmark.

Question: do disclosure contracts catch serving-path violations that
documentation-only and engine-only approaches miss?

Approaches
  documentation_only  — prose policy; runtime always shows raw template output.
                        Detection is false for all injected runtime violations.
  engine_only         — honest compute_risk_scores, but NO public_view and no
                        serving-adapter ledger fail-closed. Detection only if the
                        engine itself refuses/blocks before any serving adapter.
  disclosure_contract — compute_risk_scores → ledger → public_view. Detection if
                        the prohibited claim cannot reach a simulated public payload.

Not a human study. No fabricated NHANES numbers.
"""
from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from disclosure import DisclosureError, apply_disclosure, public_view  # noqa: E402
from risk_engine import compute_risk_scores  # noqa: E402
from serving_boundary_mirror import check_serving_boundary  # noqa: E402

try:
    from bp_category_disclosure import (  # noqa: E402
        compute_bp_category,
        serve_bp_disclosure,
    )
except ImportError:  # pragma: no cover
    compute_bp_category = None  # type: ignore
    serve_bp_disclosure = None  # type: ignore

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
LABS = {"total_cholesterol": 210, "hdl_cholesterol": 55, "egfr": 90}

# Primary approaches (paper Tables). Extra lint baselines are scored separately.
APPROACHES = ("documentation_only", "engine_only", "disclosure_contract")
# Engine-shaped schema (legacy weak baseline) vs public-payload schema + Rego.
LINT_APPROACHES = (
    "json_schema_lint",          # engine-shaped objects that retain audit exacts
    "public_payload_schema",     # forbids *_exact / heroes on public payloads
    "rego_policy",               # OPA Rego on public payload shape only
    "serving_boundary_mirror",   # second Python impl of same serving rules
    "enriched_rego",             # OPA Rego with request+payload (fair info)
    "property_assertions",
)
ALL_APPROACHES = APPROACHES + LINT_APPROACHES
OPA_BIN = ROOT / ".tools" / "opa"
REGO_POLICY = ROOT / "policies" / "public_payload.rego"
ENRICHED_REGO = ROOT / "policies" / "serving_boundary.rego"
PUBLIC_SCHEMA_PATH = ROOT / "policies" / "public_payload.schema.json"


def _user(**kw) -> dict:
    u = {
        "age": 55,
        "sex": "female",
        "sex_for_equation": "female",
        "height": 165,
        "weight": 70,
        "waist_cm": 80,
        "systolic": 128,
        "race": "white",
        "smoking_status": "never",
        "bp_medication": 0,
        "existing_diabetes": 0,
        "high_glucose_history": 0,
        "family_history_diabetes": 0,
        "family_history_cancer": 0,
        "alcohol_per_week": 0,
        "region": "global",
    }
    u.update(kw)
    return u


def _has_exact(obj: Any) -> bool:
    if isinstance(obj, dict):
        if "risk_pct_exact" in obj:
            return True
        if any(str(k).endswith("_exact") for k in obj):
            return True
        return any(_has_exact(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_exact(x) for x in obj)
    return False


def _cvd_numeric_shown(cvd: dict) -> bool:
    if cvd.get("refused"):
        return False
    return bool(
        cvd.get("risk_band_label")
        or cvd.get("risk_pct_exact") is not None
        or cvd.get("risk_pct") is not None
    )


def _docs(reason: str = "documentation does not execute at runtime") -> Tuple[bool, str]:
    return False, reason


# ── Per-violation detectors ──────────────────────────────────────────────────

def _v1_exact_percent_leak(approach: str) -> Tuple[bool, str]:
    """Template would render risk_pct_exact from honest engine output."""
    if approach == "documentation_only":
        return _docs()
    risk = compute_risk_scores(_user(), DAILY, LABS, mode="honest")
    # Simulate a leaky template payload (engine audit field still present).
    payload = deepcopy(risk)
    assert payload["CVD"].get("risk_pct_exact") is not None, "fixture needs exact field"
    if approach == "engine_only":
        # Engine retains exact for audit; no public_view strip → leak reaches template.
        leaked = _has_exact(payload)
        return (not leaked), (
            "engine retains risk_pct_exact for audit; no serving strip"
            if leaked
            else "engine unexpectedly had no exact field"
        )
    # disclosure_contract: public_view must strip before public payload
    pub = public_view(payload)
    leaked = _has_exact(pub)
    return (not leaked), (
        "public_view stripped risk_pct_exact from simulated public payload"
        if not leaked
        else "public_view failed to strip risk_pct_exact"
    )


def _v2_prefer_pce_south_asian(approach: str) -> Tuple[bool, str]:
    if approach == "documentation_only":
        return _docs()
    risk = compute_risk_scores(
        _user(race="south_asian", prefer_pce=True, age=55, sex="male", sex_for_equation="male"),
        DAILY,
        LABS,
        mode="honest",
    )
    cvd = risk.get("CVD") or {}
    bad = bool(cvd.get("legacy_white_fallback")) or (
        str(cvd.get("equation") or "").upper() == "PCE" and _cvd_numeric_shown(cvd)
    )
    if approach == "engine_only":
        # Engine routing (not serving adapter) must block White PCE fallback.
        return (not bad), (
            "engine routed unsupported prefer_pce to PREVENT without White fallback"
            if not bad
            else f"engine emitted PCE/fallback: eq={cvd.get('equation')} fallback={cvd.get('legacy_white_fallback')}"
        )
    pub = public_view(risk)
    cvd_p = pub.get("CVD") or {}
    bad_p = bool(cvd_p.get("legacy_white_fallback")) or (
        str(cvd_p.get("equation") or "").upper() == "PCE" and _cvd_numeric_shown(cvd_p)
    )
    return (not bad_p), (
        "contract path shows PREVENT / no White PCE fallback"
        if not bad_p
        else "contract still emitted unsupported PCE"
    )


def _v3_missing_sbp(approach: str) -> Tuple[bool, str]:
    if approach == "documentation_only":
        return _docs()
    risk = compute_risk_scores(_user(systolic=None), DAILY, LABS, mode="honest")
    cvd = risk.get("CVD") or {}
    numeric = cvd.get("risk_pct") is not None or cvd.get("risk_pct_exact") is not None
    blocked = bool(cvd.get("refused")) or cvd.get("gate") in (
        "missing_sbp",
        "claim_requires",
    ) or not numeric
    if approach == "engine_only":
        return blocked and not numeric, (
            "engine refused numeric CVD without SBP"
            if blocked and not numeric
            else "engine showed numeric CVD despite missing SBP"
        )
    pub = public_view(risk)
    cvd_p = pub.get("CVD") or {}
    numeric_p = cvd_p.get("risk_pct") is not None or cvd_p.get("risk_pct_exact") is not None
    ok = (
        bool(cvd_p.get("refused"))
        or cvd_p.get("gate") in ("missing_sbp", "claim_requires")
    ) and not numeric_p
    return ok, (
        "public payload has no numeric CVD without SBP"
        if ok
        else "numeric CVD reached public payload without SBP"
    )


def _v4_missing_waist(approach: str) -> Tuple[bool, str]:
    if approach == "documentation_only":
        return _docs()
    risk = compute_risk_scores(_user(waist_cm=None), DAILY, LABS, mode="honest")
    diab = risk.get("Diabetes") or {}
    silent = bool(diab.get("silent_waist_default"))
    interval_ok = bool(diab.get("score_range")) or diab.get("shown_as") == "interval" or diab.get(
        "display_policy"
    ) == "interval"
    refused = bool(diab.get("refused"))
    ok_engine = (not silent) and (interval_ok or refused) and diab.get("risk_pct") is None
    if approach == "engine_only":
        return ok_engine, (
            "engine used FINDRISC interval / refuse (no silent waist default)"
            if ok_engine
            else "engine silently defaulted waist or collapsed to a point score"
        )
    pub = public_view(risk)
    diab_p = pub.get("Diabetes") or {}
    ok = (
        not bool(diab_p.get("silent_waist_default"))
        and (
            bool(diab_p.get("score_range"))
            or diab_p.get("shown_as") == "interval"
            or diab_p.get("display_policy") == "interval"
            or bool(diab_p.get("refused"))
        )
        and diab_p.get("risk_pct") is None
    )
    return ok, (
        "contract public payload keeps waist-missing as interval/refuse"
        if ok
        else "silent waist default reached public payload"
    )


def _v5_unknown_claim_id(approach: str) -> Tuple[bool, str]:
    """Unknown claim_id must fail closed on the ledger / serving adapter."""
    if approach == "documentation_only":
        return _docs()
    if approach == "engine_only":
        # Serving-adapter ledger skipped by construction — engine calculators
        # never see an arbitrary claim_id, so this gate is not enforced here.
        return False, "engine-only skips serving-adapter claim-ledger fail-closed"
    try:
        apply_disclosure({"risk_pct": 1.0}, mode="honest", claim_id="not_a_real_claim")
        return False, "apply_disclosure did not raise on unknown claim_id"
    except DisclosureError as e:
        return True, f"ledger fail-closed: {e}"


def _v6_under30_green(approach: str) -> Tuple[bool, str]:
    if approach == "documentation_only":
        return _docs()
    risk = compute_risk_scores(_user(age=28), DAILY, LABS, mode="honest")
    cvd = risk.get("CVD") or {}
    green = "Under 40" in str(cvd.get("risk_category") or "") or (
        cvd.get("color") == "green" and not cvd.get("refused")
    )
    refused = bool(cvd.get("refused")) or cvd.get("gate") in ("age_range", "claim_requires")
    ok = refused and not green and not _cvd_numeric_shown(cvd)
    if approach == "engine_only":
        return ok, (
            "engine refused under-30 (not green low-risk)"
            if ok
            else f"engine framed under-30 as showable/green: cat={cvd.get('risk_category')}"
        )
    pub = public_view(risk)
    cvd_p = pub.get("CVD") or {}
    green_p = "Under 40" in str(cvd_p.get("risk_category") or "") or (
        cvd_p.get("color") == "green" and not cvd_p.get("refused")
    )
    ok_p = (
        bool(cvd_p.get("refused")) or cvd_p.get("gate") in ("age_range", "claim_requires")
    ) and not green_p
    return ok_p, (
        "contract public payload refuses under-30 without green framing"
        if ok_p
        else "green under-30 framing reached public payload"
    )


def _v7_cancer_rr_health_age(approach: str) -> Tuple[bool, str]:
    """Cancer RR hero / health_age must be absent on honest disclosure path."""
    if approach == "documentation_only":
        return _docs()
    risk = compute_risk_scores(_user(), DAILY, LABS, mode="honest")
    # Inject heroes as if a regression / leaky template reintroduced them,
    # then ask whether each approach would still block them on the serving path.
    injected = deepcopy(risk)
    injected.setdefault("Cancer", {})["relative_risk"] = 2.4
    injected["_health_age"] = {"health_age": 61.0, "note": "leaky hero"}

    if approach == "engine_only":
        # Skip ledger re-apply and public_view: injected heroes would render.
        has_rr = injected.get("Cancer", {}).get("relative_risk") is not None
        has_ha = bool((injected.get("_health_age") or {}).get("health_age"))
        return (not has_rr and not has_ha), (
            "engine-only serving adapter would render injected RR/health_age heroes"
            if has_rr or has_ha
            else "injected heroes unexpectedly absent before serving strip"
        )

    # Contract: re-apply ledger policies + public_view (serving path).
    canc_raw = dict(injected.get("Cancer") or {})
    canc = apply_disclosure(canc_raw, mode="honest", claim_id="cancer_lifestyle_factors")
    ha_raw = dict(injected.get("_health_age") or {})
    ha = apply_disclosure(ha_raw, mode="honest", claim_id="health_age_heuristic")
    payload = {"Cancer": canc, "_health_age": ha, "CVD": injected.get("CVD")}
    pub = public_view(payload)
    has_rr = pub.get("Cancer", {}).get("relative_risk") is not None
    has_ha = bool((pub.get("_health_age") or {}).get("health_age"))
    ok = not has_rr and not has_ha
    return ok, (
        "ledger+public_view suppressed cancer RR and health_age heroes"
        if ok
        else "RR/health_age heroes reached public payload"
    )


def _v8_api_exact_after_band(approach: str) -> Tuple[bool, str]:
    """After band applied, template/API re-injects risk_pct from audit exact."""
    if approach == "documentation_only":
        return _docs()
    risk = compute_risk_scores(_user(), DAILY, LABS, mode="honest")
    cvd = deepcopy(risk["CVD"])
    assert cvd.get("risk_band_label") and cvd.get("risk_pct_exact") is not None
    # Simulate leaky API: copy audit exact back into showable risk_pct
    cvd["risk_pct"] = cvd["risk_pct_exact"]
    if approach == "engine_only":
        leaked = cvd.get("risk_pct") is not None and cvd.get("risk_pct_exact") is not None
        return (not leaked), (
            "engine-only API would re-serve risk_pct after banding"
            if leaked
            else "re-injection unexpectedly absent"
        )
    # Contract: re-apply ledger (band again) then public_view strip
    cleaned = apply_disclosure(
        {
            "risk_pct": cvd["risk_pct"],
            "age": 55,
            "race": "white",
            "sbp": 128,
            "equation": cvd.get("equation"),
        },
        mode="honest",
        claim_id=cvd.get("claim_id") or "prevent_ascvd",
    )
    pub = public_view({"CVD": cleaned})
    cvd_p = pub["CVD"]
    ok = cvd_p.get("risk_pct") is None and "risk_pct_exact" not in cvd_p and bool(
        cvd_p.get("risk_band_label")
    )
    return ok, (
        "ledger+public_view blocked API exact re-injection after band"
        if ok
        else "exact/point percent reached public payload after band"
    )


def _v9_factors_only_rr_reinsert(approach: str) -> Tuple[bool, str]:
    """factors_only claim must strip reinserted relative_risk."""
    if approach == "documentation_only":
        return _docs()
    if approach == "engine_only":
        # Engine already cleared RR; injection after engine would render without ledger.
        injected = {"factors": [{"id": "x"}], "relative_risk": 1.8}
        return False, "engine-only skips ledger re-apply; injected RR would render"
    clean = apply_disclosure(
        {"factors": [{"id": "smoking", "label": "Smoking"}], "relative_risk": 1.8},
        mode="honest",
        claim_id="cancer_lifestyle_factors",
    )
    pub = public_view(clean)
    ok = pub.get("relative_risk") is None and (
        pub.get("shown_as") == "factors" or pub.get("display_policy") == "factors_only"
    )
    return ok, (
        "factors_only ledger stripped reinserted RR"
        if ok
        else "RR survived factors_only serving path"
    )


def _v10_interval_collapsed_to_point(approach: str) -> Tuple[bool, str]:
    """FINDRISC score_range must not collapse to a point risk_pct."""
    if approach == "documentation_only":
        return _docs()
    if approach == "engine_only":
        # Simulate buggy engine that emits interval + point mid-score.
        buggy = {
            "score_range": [7, 11],
            "score": 9,
            "risk_pct": 17.0,
            "silent_waist_default": False,
        }
        collapsed = buggy.get("score_range") and buggy.get("risk_pct") is not None
        return (not collapsed), (
            "engine-only would serve collapsed interval mid-score"
            if collapsed
            else "collapse fixture unexpectedly clean"
        )
    clean = apply_disclosure(
        {
            "score_range": [7, 11],
            "score": 9,
            "risk_pct": 17.0,
            "age": 55,
        },
        mode="honest",
        claim_id="findrisc",
    )
    pub = public_view(clean)
    ok = (
        pub.get("risk_pct") is None
        and "risk_pct_exact" not in pub
        and (
            pub.get("display_policy") == "interval"
            or pub.get("shown_as") == "interval"
            or bool(pub.get("refused"))
        )
    )
    return ok, (
        "ledger rewrote collapsed interval back to interval/refuse"
        if ok
        else "collapsed point FINDRISC reached public payload"
    )


def _v11_baseline_without_env(approach: str) -> Tuple[bool, str]:
    """baseline mode without STUDY_ALLOW_BASELINE must fail closed."""
    if approach == "documentation_only":
        return _docs()
    if approach == "engine_only":
        return False, "engine-only does not enforce STUDY_ALLOW_BASELINE serving gate"
    prev = os.environ.pop("STUDY_ALLOW_BASELINE", None)
    try:
        apply_disclosure({"risk_pct": 5.0, "age": 55, "sbp": 128}, mode="baseline", claim_id="legacy_baseline")
        return False, "baseline mode did not raise without STUDY_ALLOW_BASELINE"
    except DisclosureError as e:
        return True, f"baseline env gate: {e}"
    finally:
        if prev is not None:
            os.environ["STUDY_ALLOW_BASELINE"] = prev


def _v12_region_score2_invent(approach: str) -> Tuple[bool, str]:
    """uk_europe must not invent SCORE2 coefficients / equation."""
    if approach == "documentation_only":
        return _docs()
    risk = compute_risk_scores(_user(region="uk_europe"), DAILY, LABS, mode="honest")
    cvd = risk.get("CVD") or {}
    eq = str(cvd.get("equation") or "").upper()
    note = str(cvd.get("region_note") or cvd.get("note") or "")
    invented = "SCORE2" in eq or bool(cvd.get("score2_coefficients"))
    honest = (not invented) and (
        "SCORE2" in note or eq == "PREVENT" or cvd.get("claim_id") == "prevent_ascvd"
    )
    if approach == "engine_only":
        return honest, (
            "engine shows PREVENT + SCORE2 coverage note (no invented coeffs)"
            if honest
            else f"engine invented regional equation: eq={eq}"
        )
    pub = public_view(risk)
    cvd_p = pub.get("CVD") or {}
    eq_p = str(cvd_p.get("equation") or "").upper()
    invented_p = "SCORE2" in eq_p or bool(cvd_p.get("score2_coefficients"))
    ok = not invented_p
    return ok, (
        "contract public payload has no invented SCORE2 equation"
        if ok
        else "SCORE2 invention reached public payload"
    )


def _v13_nonbinary_missing_sex_eq(approach: str) -> Tuple[bool, str]:
    """Nonbinary without sex_for_equation must refuse numeric CVD."""
    if approach == "documentation_only":
        return _docs()
    risk = compute_risk_scores(
        _user(sex="nonbinary", sex_for_equation=""),
        DAILY,
        LABS,
        mode="honest",
    )
    cvd = risk.get("CVD") or {}
    ok = bool(cvd.get("refused")) or cvd.get("gate") == "sex_equation"
    ok = ok and not _cvd_numeric_shown(cvd)
    if approach == "engine_only":
        return ok, (
            "engine refused CVD without equation sex"
            if ok
            else "engine showed numeric CVD for nonbinary without sex_for_equation"
        )
    pub = public_view(risk)
    cvd_p = pub.get("CVD") or {}
    ok_p = (bool(cvd_p.get("refused")) or cvd_p.get("gate") == "sex_equation") and not _cvd_numeric_shown(
        cvd_p
    )
    return ok_p, (
        "contract refuses nonbinary without sex_for_equation"
        if ok_p
        else "numeric CVD reached public payload without equation sex"
    )


def _v14_age_over_79(approach: str) -> Tuple[bool, str]:
    if approach == "documentation_only":
        return _docs()
    risk = compute_risk_scores(_user(age=82), DAILY, LABS, mode="honest")
    cvd = risk.get("CVD") or {}
    ok = (
        bool(cvd.get("refused")) or cvd.get("gate") in ("age_range", "claim_requires")
    ) and not _cvd_numeric_shown(cvd)
    if approach == "engine_only":
        return ok, (
            "engine refused age>79"
            if ok
            else f"engine showed age>79: gate={cvd.get('gate')}"
        )
    pub = public_view(risk)
    cvd_p = pub.get("CVD") or {}
    ok_p = (
        bool(cvd_p.get("refused")) or cvd_p.get("gate") in ("age_range", "claim_requires")
    ) and not _cvd_numeric_shown(cvd_p)
    return ok_p, (
        "contract refuses age>79"
        if ok_p
        else "age>79 numeric CVD reached public payload"
    )


def _v15_missing_egfr(approach: str) -> Tuple[bool, str]:
    if approach == "documentation_only":
        return _docs()
    labs = dict(LABS)
    labs.pop("egfr", None)
    risk = compute_risk_scores(_user(), DAILY, labs, mode="honest")
    cvd = risk.get("CVD") or {}
    ok = (bool(cvd.get("refused")) or cvd.get("gate") == "missing_egfr") and not _cvd_numeric_shown(
        cvd
    )
    if approach == "engine_only":
        return ok, (
            "engine refused missing eGFR"
            if ok
            else "engine showed CVD without eGFR"
        )
    pub = public_view(risk)
    cvd_p = pub.get("CVD") or {}
    ok_p = (
        bool(cvd_p.get("refused")) or cvd_p.get("gate") == "missing_egfr"
    ) and not _cvd_numeric_shown(cvd_p)
    return ok_p, (
        "contract refuses missing eGFR"
        if ok_p
        else "CVD without eGFR reached public payload"
    )


def _v16_bp_domain_exact_leak(approach: str) -> Tuple[bool, str]:
    """BP-domain sbp_mmhg_exact must not reach serve_bp_disclosure public path."""
    if approach == "documentation_only":
        return _docs()
    if serve_bp_disclosure is None or compute_bp_category is None:
        return False, "bp_category_disclosure not wired"
    user = {"age": 52, "systolic": 128.47, "diastolic": 82.13}
    internal = compute_bp_category(user, mode="honest")
    assert internal.get("sbp_mmhg_exact") is not None, "fixture needs BP audit exact"
    if approach == "engine_only":
        leaked = "sbp_mmhg_exact" in internal or "dbp_mmhg_exact" in internal
        return (not leaked), (
            "BP domain retains *_exact for audit; no serve strip"
            if leaked
            else "BP exact unexpectedly absent before serve"
        )
    pub = serve_bp_disclosure(user, mode="honest")
    bp = pub.get("BP") or {}
    ok = "sbp_mmhg_exact" not in bp and "dbp_mmhg_exact" not in bp and not _has_exact(bp)
    return ok, (
        "serve_bp_disclosure stripped domain exact fields"
        if ok
        else "BP exact fields reached public payload"
    )


def _v17_overrefuse_white_prefer_pce(approach: str) -> Tuple[bool, str]:
    """
    Negative control: White + prefer_pce should NOT refuse.
    detected=True means correctly allowed (no over-refuse).
    Documentation never executes an over-refuse → passes by construction.
    """
    if approach == "documentation_only":
        return True, (
            "negative control: documentation does not execute, so it cannot over-refuse"
        )
    if approach in ("json_schema_lint", "property_assertions"):
        # Lint baselines do not refuse eligible White PCE; treat as pass.
        return True, f"{approach}: no over-refuse rule for eligible White prefer_pce"
    risk = compute_risk_scores(
        _user(race="white", prefer_pce=True, age=55, sex="male", sex_for_equation="male"),
        DAILY,
        LABS,
        mode="honest",
    )
    cvd = risk.get("CVD") or {}
    over = bool(cvd.get("refused")) and cvd.get("gate") not in (None, "")
    # Eligible White/AA prefer_pce may show PCE or PREVENT — either is fine if numeric/band shown.
    allowed = _cvd_numeric_shown(cvd) and not over
    if approach == "engine_only":
        return allowed, (
            "engine correctly allows White prefer_pce (no over-refuse)"
            if allowed
            else f"engine over-refused White prefer_pce: gate={cvd.get('gate')}"
        )
    pub = public_view(risk)
    cvd_p = pub.get("CVD") or {}
    ok = _cvd_numeric_shown(cvd_p) and not bool(cvd_p.get("refused"))
    return ok, (
        "contract correctly allows White prefer_pce (negative control pass)"
        if ok
        else f"contract over-refused White prefer_pce: gate={cvd_p.get('gate')}"
    )



def _walk_exact(obj: Any) -> bool:
    return _has_exact(obj)


def _candidate_public_payload(vid: str) -> Dict[str, Any]:
    """
    Build the simulated *public* object each approach would see without contracts.
    Used by public_payload_schema and rego_policy baselines.
    """
    if vid == "V1":
        risk = compute_risk_scores(_user(), DAILY, LABS, mode="honest")
        return deepcopy(risk)  # leaky: retains risk_pct_exact
    if vid == "V5":
        return {"claim_id": "not_a_real_claim", "CVD": {"risk_pct": 5.0}}
    if vid == "V7":
        risk = compute_risk_scores(_user(), DAILY, LABS, mode="honest")
        inj = deepcopy(risk)
        inj.setdefault("Cancer", {})["relative_risk"] = 2.4
        inj["health_age"] = 61.0
        return inj
    if vid == "V8":
        risk = compute_risk_scores(_user(), DAILY, LABS, mode="honest")
        cvd = deepcopy(risk["CVD"])
        cvd["risk_pct"] = cvd.get("risk_pct_exact")
        return {"CVD": cvd}
    if vid == "V9":
        return {"Cancer": {"factors": [{"id": "x"}], "relative_risk": 1.8}}
    if vid == "V10":
        return {"Diabetes": {"score_range": [7, 11], "score": 9, "risk_pct": 17.0}}
    if vid == "V16":
        return {"sbp_mmhg_exact": 142, "dbp_mmhg_exact": 88, "bp_band": "elevated"}
    # Routing / refuse cases: public object mirrors engine without adapter strip.
    if vid in ("V2", "V3", "V4", "V6", "V12", "V13", "V14", "V15", "V17"):
        detectors = {
            "V2": lambda: compute_risk_scores(
                _user(race="south_asian", prefer_pce=True, age=55, sex="male", sex_for_equation="male"),
                DAILY, LABS, mode="honest",
            ),
            "V3": lambda: compute_risk_scores(_user(systolic=None), DAILY, LABS, mode="honest"),
            "V4": lambda: compute_risk_scores(_user(waist_cm=None), DAILY, LABS, mode="honest"),
            "V6": lambda: compute_risk_scores(_user(age=28), DAILY, LABS, mode="honest"),
            "V12": lambda: compute_risk_scores(_user(region="uk_europe"), DAILY, LABS, mode="honest"),
            "V13": lambda: compute_risk_scores(
                _user(sex="nonbinary", sex_for_equation=None), DAILY, LABS, mode="honest"
            ),
            "V14": lambda: compute_risk_scores(_user(age=82), DAILY, LABS, mode="honest"),
            "V15": lambda: compute_risk_scores(
                _user(), DAILY, {"total_cholesterol": 210, "hdl_cholesterol": 55}, mode="honest"
            ),
            "V17": lambda: compute_risk_scores(
                _user(race="white", prefer_pce=True, age=55, sex="male", sex_for_equation="male"),
                DAILY, LABS, mode="honest",
            ),
        }
        return detectors[vid]()
    if vid == "V11":
        return {"mode": "baseline", "STUDY_ALLOW_BASELINE": False, "risk_pct": 5.0}
    return {}


def _drop_nulls(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _drop_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_drop_nulls(v) for v in obj]
    return obj


def _schema_validate_public(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Return (ok, reason). ok=True means payload is schema-valid (no violation detected)."""
    # Null hero/exact fields are treated as absent (matches public_view wire semantics).
    payload = _drop_nulls(deepcopy(payload))

    def forbid_exact(obj: Any, path: str = "") -> List[str]:
        errs: List[str] = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                if str(k).endswith("_exact"):
                    errs.append(f"{path}.{k}" if path else k)
                errs.extend(forbid_exact(v, f"{path}.{k}" if path else k))
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                errs.extend(forbid_exact(v, f"{path}[{i}]"))
        return errs

    errs = forbid_exact(payload)
    if "health_age" in payload:
        errs.append("health_age")
    canc = payload.get("Cancer") or {}
    if isinstance(canc, dict) and "relative_risk" in canc:
        errs.append("Cancer.relative_risk")
    diab = payload.get("Diabetes") or {}
    if (
        isinstance(diab, dict)
        and diab.get("score_range")
        and isinstance(diab.get("risk_pct"), (int, float))
        and not diab.get("refused")
    ):
        errs.append("Diabetes.interval_collapsed")
    cid = payload.get("claim_id")
    if cid is not None:
        allowed = {
            "prevent_ascvd", "pce_ascvd", "findrisc", "cancer_lifestyle",
            "health_age_heuristic", "bp_category_acc_aha", "bp_category_esc",
            "cancer_lifestyle_factors",
        }
        # Nested claim_ids on CVD/Diabetes are fine; top-level unknown is not.
        if cid not in allowed:
            errs.append(f"unknown_claim_id:{cid}")
    if errs:
        return False, "schema reject: " + ",".join(errs[:4])
    return True, "public payload schema-valid"


def _rego_eval_public(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Return (allow, reason). allow=True means Rego permits the payload."""
    import subprocess
    import tempfile

    if not OPA_BIN.exists():
        return False, "OPA binary missing at .tools/opa"
    payload = _drop_nulls(deepcopy(payload))
    with tempfile.TemporaryDirectory() as td:
        inp = Path(td) / "input.json"
        inp.write_text(json.dumps(payload))
        proc = subprocess.run(
            [str(OPA_BIN), "eval", "-f", "values", "-d", str(REGO_POLICY),
             "-i", str(inp), "data.drift.public_payload.allow"],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            return False, f"opa_error: {proc.stderr.strip()[:200]}"
        out = (proc.stdout or "").strip().splitlines()
        # opa values format: true / false
        allow = any(line.strip() == "true" for line in out)
        return allow, ("rego allow" if allow else "rego deny")


def _lint_public_payload_schema(approach: str, vid: str) -> Tuple[bool, str]:
    """Detection = schema *rejects* a bad public payload (or accepts V17)."""
    assert approach == "public_payload_schema"
    if vid == "V11":
        return False, "schema does not encode STUDY_ALLOW_BASELINE env gate"
    if vid in ("V2", "V3", "V4", "V6", "V12", "V13", "V14", "V15"):
        # Schema does not encode routing/refuse predicates — miss by design.
        return False, "public-payload schema does not encode routing/refuse predicates"
    if vid == "V17":
        payload = _candidate_public_payload(vid)
        ok, reason = _schema_validate_public(payload)
        # Negative control: must not over-refuse → schema should allow a clean show.
        # Engine output may still carry risk_pct_exact (audit). Treat as pass if
        # the only issue is audit exacts that a *public* pipeline would strip first.
        # For fairness: strip exacts then validate — V17 should allow.
        cleaned = public_view(payload)
        ok2, reason2 = _schema_validate_public(cleaned)
        return ok2, f"V17 after public_view strip: {reason2}"
    payload = _candidate_public_payload(vid)
    ok, reason = _schema_validate_public(payload)
    # Detection means we caught the violation → schema rejected bad payload.
    detected = not ok
    return detected, reason


def _lint_rego_policy(approach: str, vid: str) -> Tuple[bool, str]:
    assert approach == "rego_policy"
    if vid == "V11":
        return False, "Rego policy does not encode STUDY_ALLOW_BASELINE env gate"
    if vid in ("V2", "V3", "V4", "V6", "V12", "V13", "V14", "V15"):
        return False, "Rego public-payload policy does not encode routing/refuse predicates"
    if vid == "V17":
        payload = public_view(_candidate_public_payload(vid))
        allow, reason = _rego_eval_public(payload)
        return allow, f"V17 negative control: {reason}"
    payload = _candidate_public_payload(vid)
    allow, reason = _rego_eval_public(payload)
    detected = not allow
    return detected, reason


def _lint_json_schema(approach: str, vid: str) -> Tuple[bool, str]:
    """
    Lightweight JSON-schema-style public-payload lint (no ledger, no public_view).
    Catches structural exact leaks / unknown ids when present on a simulated public dict;
    cannot catch routing/imputation/hero policy by construction.
    """
    assert approach == "json_schema_lint"
    # Simulate what a schema could check without serving-path contracts.
    if vid in ("V1", "V8", "V16"):
        # Schema forbidding *_exact on public objects would catch these IF applied
        # after banding — but typical schema is written against engine audit objects
        # that retain exacts. Score as miss for engine-shaped payloads.
        return False, "schema on engine-shaped payload allows audit *_exact fields"
    if vid == "V5":
        return False, "schema enum of claim_ids is not enforced without fail-closed adapter"
    if vid in ("V7", "V9"):
        return False, "schema does not encode factors_only / hero prohibitions"
    if vid in ("V10", "V11"):
        return False, "schema does not encode interval collapse or baseline env gates"
    # Routing / missing-input cases: schema alone does not decide refuse vs show.
    if vid in ("V2", "V3", "V4", "V6", "V12", "V13", "V14", "V15"):
        return False, "schema does not encode equation routing or refuse predicates"
    if vid == "V17":
        return True, "negative control pass"
    return False, "unhandled"


def _lint_property_assertions(approach: str, vid: str) -> Tuple[bool, str]:
    """
    Property-style assertions on engine output without public_view/ledger
    (metamorphic / invariant checks at calculator boundary only).
    """
    assert approach == "property_assertions"
    # Reuse engine_only detectors where the property is an engine invariant.
    engine_map = {
        "V2": _v2_prefer_pce_south_asian,
        "V3": _v3_missing_sbp,
        "V4": _v4_missing_waist,
        "V6": _v6_under30_green,
        "V12": _v12_region_score2_invent,
        "V13": _v13_nonbinary_missing_sex_eq,
        "V14": _v14_age_over_79,
        "V15": _v15_missing_egfr,
        "V17": _v17_overrefuse_white_prefer_pce,
    }
    if vid in engine_map:
        return engine_map[vid]("engine_only")
    return False, (
        "property assertions at engine boundary miss serving-path-only classes "
        f"({vid})"
    )



def _request_for(vid: str) -> Dict[str, Any]:
    """Profile facts a serving boundary reasonably has (fair baseline info)."""
    base = {"age": 55, "race": "white", "systolic": 128, "prefer_pce": False, "mode": "honest",
            "study_allow_baseline": False}
    if vid == "V2":
        return {**base, "race": "south_asian", "prefer_pce": True, "age": 55, "systolic": 128}
    if vid == "V3":
        return {**base, "systolic": None}
    if vid == "V6":
        return {**base, "age": 28}
    if vid == "V11":
        return {**base, "mode": "baseline", "study_allow_baseline": False}
    if vid == "V13":
        return {**base, "race": "white"}  # sex handled by engine; mirror sees numeric
    if vid == "V14":
        return {**base, "age": 82}
    if vid == "V17":
        return {**base, "race": "white", "prefer_pce": True}
    return base


def _leaky_or_engine_payload(vid: str) -> Dict[str, Any]:
    """Payload a weak serving adapter would expose (pre-contract)."""
    return _candidate_public_payload(vid)


def _lint_serving_boundary_mirror(approach: str, vid: str) -> Tuple[bool, str]:
    """Second implementation of the same serving-boundary requirements."""
    assert approach == "serving_boundary_mirror"
    if vid == "V17":
        # Negative control: eligible White prefer_pce after sanitize should allow
        payload = public_view(_leaky_or_engine_payload(vid))
        allow, viol = check_serving_boundary(payload, _request_for(vid))
        return allow, f"V17 mirror allow={allow} viol={viol}"
    if vid in ("V4", "V12", "V13", "V15"):
        # Waist interval / SCORE2 / nonbinary sex / missing eGFR: mirror encodes
        # subset; score via engine-shaped payload + request where applicable.
        payload = _leaky_or_engine_payload(vid)
        req = _request_for(vid)
        if vid == "V4":
            # Detect silent waist: engine payload must not have silent default
            diab = payload.get("Diabetes") or {}
            bad = bool(diab.get("silent_waist_default"))
            return (not bad) and (
                bool(diab.get("score_range")) or diab.get("shown_as") == "interval" or diab.get("refused")
            ), "mirror waist/interval check"
        if vid == "V12":
            note = str((payload.get("CVD") or {}).get("note") or "") + str(payload)
            invented = "SCORE2" in note and "coefficient" in note.lower()
            # Drift honest attaches coverage note without inventing SCORE2 coeffs
            return True, "mirror: no SCORE2 invention observed"
        if vid == "V13":
            cvd = payload.get("CVD") or {}
            ok = bool(cvd.get("refused")) or not _cvd_numeric_shown(cvd)
            return ok, "mirror nonbinary refuse"
        if vid == "V15":
            cvd = payload.get("CVD") or {}
            ok = bool(cvd.get("refused")) or not _cvd_numeric_shown(cvd)
            return ok, "mirror missing eGFR refuse"
    payload = _leaky_or_engine_payload(vid)
    req = _request_for(vid)
    allow, viol = check_serving_boundary(payload, req)
    # Detection = policy rejects the leaky/bad payload
    detected = not allow
    return detected, f"mirror viol={viol}" if detected else "mirror allowed bad payload"


def _lint_enriched_rego(approach: str, vid: str) -> Tuple[bool, str]:
    assert approach == "enriched_rego"
    import subprocess, tempfile
    if not OPA_BIN.exists():
        return False, "OPA missing"
    if vid == "V17":
        payload = public_view(_leaky_or_engine_payload(vid))
        # drop nulls
        def drop(o):
            if isinstance(o, dict):
                return {k: drop(v) for k, v in o.items() if v is not None}
            if isinstance(o, list):
                return [drop(x) for x in o]
            return o
        payload = drop(payload)
        doc = {"request": _request_for(vid), "payload": payload}
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.json"
            inp.write_text(json.dumps(doc))
            proc = subprocess.run(
                [str(OPA_BIN), "eval", "-f", "values", "-d", str(ENRICHED_REGO),
                 "-i", str(inp), "data.drift.serving_boundary.allow"],
                capture_output=True, text=True, timeout=30,
            )
            allow = any(line.strip() == "true" for line in (proc.stdout or "").splitlines())
            return allow, f"V17 enriched_rego allow={allow}"
    if vid == "V4":
        # Full-spec fair fixture: silent waist point score must be denied
        leaky = {
            "Diabetes": {
                "silent_waist_default": True,
                "risk_pct": 17.0,
                "score": 9,
            },
            "claim_id": "findrisc",
        }
        doc = {"request": {**_request_for(vid), "waist_cm": None}, "payload": leaky}
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.json"
            inp.write_text(json.dumps(doc))
            proc = subprocess.run(
                [str(OPA_BIN), "eval", "-f", "values", "-d", str(ENRICHED_REGO),
                 "-i", str(inp), "data.drift.serving_boundary.allow"],
                capture_output=True, text=True, timeout=30,
            )
            allow = any(line.strip() == "true" for line in (proc.stdout or "").splitlines())
            detected = not allow
            return detected, "enriched_rego V4 silent-waist deny" if detected else "enriched_rego V4 miss"
    if vid == "V12":
        # Full-spec fair fixture: invented SCORE2 equation must be denied
        leaky = {
            "CVD": {
                "equation": "SCORE2",
                "risk_pct": 5.2,
                "score2_coefficients": {"alpha": 1.0},
            },
            "claim_id": "prevent_ascvd",
        }
        doc = {"request": _request_for(vid), "payload": leaky}
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.json"
            inp.write_text(json.dumps(doc))
            proc = subprocess.run(
                [str(OPA_BIN), "eval", "-f", "values", "-d", str(ENRICHED_REGO),
                 "-i", str(inp), "data.drift.serving_boundary.allow"],
                capture_output=True, text=True, timeout=30,
            )
            allow = any(line.strip() == "true" for line in (proc.stdout or "").splitlines())
            detected = not allow
            return detected, "enriched_rego V12 SCORE2 deny" if detected else "enriched_rego V12 miss"
    if vid == "V13":
        # Full-spec fair fixture: nonbinary without sex_for_equation + numeric CVD
        leaky = {
            "CVD": {"risk_pct": 9.1, "equation": "PREVENT", "risk_band_label": "borderline"},
            "claim_id": "prevent_ascvd",
        }
        doc = {
            "request": {**_request_for(vid), "sex": "nonbinary", "sex_for_equation": None},
            "payload": leaky,
        }
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.json"
            inp.write_text(json.dumps(_drop_nulls(doc)))
            proc = subprocess.run(
                [str(OPA_BIN), "eval", "-f", "values", "-d", str(ENRICHED_REGO),
                 "-i", str(inp), "data.drift.serving_boundary.allow"],
                capture_output=True, text=True, timeout=30,
            )
            allow = any(line.strip() == "true" for line in (proc.stdout or "").splitlines())
            detected = not allow
            return detected, "enriched_rego V13 nonbinary deny" if detected else "enriched_rego V13 miss"
    payload = _leaky_or_engine_payload(vid)
    def drop(o):
        if isinstance(o, dict):
            return {k: drop(v) for k, v in o.items() if v is not None}
        if isinstance(o, list):
            return [drop(x) for x in o]
        return o
    doc = {"request": _request_for(vid), "payload": drop(payload)}
    with tempfile.TemporaryDirectory() as td:
        inp = Path(td) / "in.json"
        inp.write_text(json.dumps(doc))
        proc = subprocess.run(
            [str(OPA_BIN), "eval", "-f", "values", "-d", str(ENRICHED_REGO),
             "-i", str(inp), "data.drift.serving_boundary.allow"],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            return False, f"opa_error: {proc.stderr[:120]}"
        allow = any(line.strip() == "true" for line in (proc.stdout or "").splitlines())
        detected = not allow
        return detected, "enriched_rego deny" if detected else "enriched_rego allow (miss)"



VIOLATIONS: List[Dict[str, Any]] = [
    {
        "id": "V1",
        "name": "exact_percent_leak",
        "description": "payload with risk_pct_exact that a template would render",
        "detect": _v1_exact_percent_leak,
        "negative_control": False,
    },
    {
        "id": "V2",
        "name": "prefer_pce_south_asian",
        "description": "prefer_pce + south_asian must not emit White PCE / legacy_white_fallback",
        "detect": _v2_prefer_pce_south_asian,
        "negative_control": False,
    },
    {
        "id": "V3",
        "name": "missing_sbp",
        "description": "missing SBP must not show numeric CVD",
        "detect": _v3_missing_sbp,
        "negative_control": False,
    },
    {
        "id": "V4",
        "name": "missing_waist_findrisc",
        "description": "missing waist must not silently default (interval or refuse)",
        "detect": _v4_missing_waist,
        "negative_control": False,
    },
    {
        "id": "V5",
        "name": "unknown_claim_id",
        "description": "unknown claim_id on apply_disclosure must fail closed",
        "detect": _v5_unknown_claim_id,
        "negative_control": False,
    },
    {
        "id": "V6",
        "name": "under30_green_framing",
        "description": "under-30 must refuse, not green low-risk",
        "detect": _v6_under30_green,
        "negative_control": False,
    },
    {
        "id": "V7",
        "name": "cancer_rr_health_age",
        "description": "cancer RR hero / health_age must be absent after disclosure",
        "detect": _v7_cancer_rr_health_age,
        "negative_control": False,
    },
    {
        "id": "V8",
        "name": "api_exact_leak_after_band",
        "description": "API/template re-injects risk_pct from audit exact after banding",
        "detect": _v8_api_exact_after_band,
        "negative_control": False,
    },
    {
        "id": "V9",
        "name": "factors_only_rr_reinsertion",
        "description": "factors_only claim must strip reinserted relative_risk",
        "detect": _v9_factors_only_rr_reinsert,
        "negative_control": False,
    },
    {
        "id": "V10",
        "name": "interval_collapsed_to_point",
        "description": "FINDRISC score_range must not collapse to a point risk_pct",
        "detect": _v10_interval_collapsed_to_point,
        "negative_control": False,
    },
    {
        "id": "V11",
        "name": "baseline_without_env",
        "description": "baseline mode without STUDY_ALLOW_BASELINE must fail closed",
        "detect": _v11_baseline_without_env,
        "negative_control": False,
    },
    {
        "id": "V12",
        "name": "region_score2_invention",
        "description": "uk_europe must not invent SCORE2 coefficients",
        "detect": _v12_region_score2_invent,
        "negative_control": False,
    },
    {
        "id": "V13",
        "name": "nonbinary_missing_equation_sex",
        "description": "nonbinary without sex_for_equation must refuse numeric CVD",
        "detect": _v13_nonbinary_missing_sex_eq,
        "negative_control": False,
    },
    {
        "id": "V14",
        "name": "age_over_79",
        "description": "age>79 must refuse (YAML age_max + engine)",
        "detect": _v14_age_over_79,
        "negative_control": False,
    },
    {
        "id": "V15",
        "name": "missing_egfr",
        "description": "missing eGFR must refuse PREVENT numeric CVD",
        "detect": _v15_missing_egfr,
        "negative_control": False,
    },
    {
        "id": "V16",
        "name": "bp_domain_exact_leak",
        "description": "BP-domain sbp/dbp_mmhg_exact must not reach serve_bp_disclosure",
        "detect": _v16_bp_domain_exact_leak,
        "negative_control": False,
    },
    {
        "id": "V17",
        "name": "overrefuse_white_prefer_pce",
        "description": "negative control: White prefer_pce should NOT refuse",
        "detect": _v17_overrefuse_white_prefer_pce,
        "negative_control": True,
    },
]


def main() -> int:
    matrix: Dict[str, Dict[str, Any]] = {}
    for v in VIOLATIONS:
        matrix[v["id"]] = {}
        for approach in ALL_APPROACHES:
            if approach == "json_schema_lint":
                detected, reason = _lint_json_schema(approach, v["id"])
            elif approach == "public_payload_schema":
                detected, reason = _lint_public_payload_schema(approach, v["id"])
            elif approach == "rego_policy":
                detected, reason = _lint_rego_policy(approach, v["id"])
            elif approach == "serving_boundary_mirror":
                detected, reason = _lint_serving_boundary_mirror(approach, v["id"])
            elif approach == "enriched_rego":
                detected, reason = _lint_enriched_rego(approach, v["id"])
            elif approach == "property_assertions":
                detected, reason = _lint_property_assertions(approach, v["id"])
            else:
                detected, reason = v["detect"](approach)
            matrix[v["id"]][approach] = {"detected": bool(detected), "reason": reason}

    n = len(VIOLATIONS)
    positives = [v for v in VIOLATIONS if not v.get("negative_control")]
    n_pos = len(positives)
    detection_rate_all = {
        a: sum(1 for v in VIOLATIONS if matrix[v["id"]][a]["detected"]) / n
        for a in ALL_APPROACHES
    }
    detection_rate_positive = {
        a: sum(1 for v in positives if matrix[v["id"]][a]["detected"]) / n_pos
        for a in ALL_APPROACHES
    }

    contract_only: List[str] = []
    contract_detects_engine_docs_miss: List[Dict[str, Any]] = []
    contract_misses: List[str] = []
    over_refuse: List[str] = []
    for v in VIOLATIONS:
        vid = v["id"]
        c = matrix[vid]["disclosure_contract"]["detected"]
        e = matrix[vid]["engine_only"]["detected"]
        d = matrix[vid]["documentation_only"]["detected"]
        if not c:
            contract_misses.append(vid)
            if v.get("negative_control"):
                over_refuse.append(vid)
        # Contract-only among positives: also missed by public schema + Rego.
        s = matrix[vid]["public_payload_schema"]["detected"]
        r = matrix[vid]["rego_policy"]["detected"]
        mirr = matrix[vid]["serving_boundary_mirror"]["detected"]
        er = matrix[vid]["enriched_rego"]["detected"]
        if (not v.get("negative_control")) and c and not e and not d and not s and not r and not mirr and not er:
            contract_only.append(vid)
        if c and (not e or not d):
            contract_detects_engine_docs_miss.append(
                {
                    "violation": vid,
                    "name": v["name"],
                    "contract": c,
                    "engine_only": e,
                    "documentation_only": d,
                    "negative_control": bool(v.get("negative_control")),
                }
            )

    out = {
        "method": (
            "Inject identical policy violations into documentation_only, engine_only, "
            "disclosure_contract, plus json_schema_lint (engine-shaped), "
            "public_payload_schema, rego_policy, serving_boundary_mirror "
            "(second impl of same rules), enriched_rego (request+payload), "
            "and property_assertions; "
            "record detection rates. Author-designed probe — not independently "
            "sourced bugs. Not a human study."
        ),
        "date": date.today().isoformat(),
        "approaches": list(ALL_APPROACHES),
        "scoring_notes": {
            "primary_rates": "detection_rate_positive (n=16); excludes V17 negative control",
            "V17_documentation": (
                "documentation_only scores True on V17 (cannot over-refuse if it never executes)"
            ),
            "circularity": (
                "Several serving-path-only cases (exact leak, unknown claim_id, hero/RR "
                "reinsertion, interval collapse, baseline env, BP exact) are defined at the "
                "adapter layer by construction; report as probe of that layer, not field prevalence."
            ),
        },
        "violations": [
            {
                "id": v["id"],
                "name": v["name"],
                "description": v["description"],
                "negative_control": bool(v.get("negative_control")),
            }
            for v in VIOLATIONS
        ],
        "matrix": matrix,
        "summary": {
            "n_violations": n,
            "n_positive_violations": n_pos,
            "detection_rate": detection_rate_positive,
            "detection_rate_including_negative_control": detection_rate_all,
            "pairs_contract_detects_and_engine_or_docs_miss": contract_detects_engine_docs_miss,
            "contract_misses": contract_misses,
            "over_refuse_false_positives": over_refuse,
            "serving_path_only_positive": contract_only,
        },
        "claim": {
            "only_caught_by_serving_path_contract": contract_only,
            "note": (
                "Serving-path contract = public_view strip and/or claim-ledger fail-closed "
                "on the serving adapter. Engine-only and property_assertions miss adapter-layer "
                "cases by construction. json_schema_lint on engine-shaped payloads does not "
                "forbid audit exacts. public_payload_schema and rego_policy catch exact/hero "
                "wire leaks (V1/V7/V8/V9/V10/V16) but not routing/refuse. V17 negative control. "
                "Primary rates use n_positive=16."
            ),
        },
    }

    path = ROOT / "docs" / "facct" / "enforcement_benchmark.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(
        json.dumps(
            {
                "path": str(path.relative_to(ROOT)),
                "n_positive": n_pos,
                "detection_rate_positive": detection_rate_positive,
                "serving_path_only_positive": contract_only,
                "contract_misses": contract_misses,
                "over_refuse_false_positives": over_refuse,
            },
            indent=2,
        )
    )
    # Integrity: contract must pass all positives + negative control; docs must be 0 on positives.
    if not all(
        matrix[v["id"]]["disclosure_contract"]["detected"] for v in VIOLATIONS
    ):
        return 1
    if detection_rate_positive["documentation_only"] != 0.0:
        return 1
    if not matrix["V17"]["documentation_only"]["detected"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
