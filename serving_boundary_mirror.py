"""
Second implementation of consumer serving-boundary disclosure rules.

Does NOT import disclosure.public_view or apply_disclosure — intentional
duplicate of the policy surface for fair baseline comparison (same requirements,
independent code path).
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

PCE_RACES = {"white", "aa"}
KNOWN_CLAIMS = {
    "prevent_ascvd",
    "pce_ascvd",
    "findrisc",
    "cancer_lifestyle",
    "cancer_lifestyle_factors",
    "health_age_heuristic",
    "bp_category_acc_aha",
    "bp_category_esc",
    "legacy_baseline",
}


def _walk_exact(obj: Any) -> bool:
    if isinstance(obj, dict):
        if any(str(k).endswith("_exact") for k in obj):
            return True
        return any(_walk_exact(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_walk_exact(x) for x in obj)
    return False


def _cvd_numeric(cvd: dict) -> bool:
    if not cvd or cvd.get("refused"):
        return False
    return (
        cvd.get("risk_pct") is not None
        or cvd.get("risk_pct_exact") is not None
        or bool(cvd.get("risk_band_label"))
    )


def sanitize_public(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Strip *_exact and null out banned heroes (mirror of public_view intent)."""
    out = deepcopy(payload)

    def strip(o: Any) -> Any:
        if isinstance(o, dict):
            return {
                k: strip(v)
                for k, v in o.items()
                if not str(k).endswith("_exact") and k not in ("_audit_exact",)
            }
        if isinstance(o, list):
            return [strip(x) for x in o]
        return o

    out = strip(out)
    if "health_age" in out and out["health_age"] is not None:
        out["health_age"] = None
    canc = out.get("Cancer")
    if isinstance(canc, dict) and canc.get("relative_risk") is not None:
        canc = dict(canc)
        canc["relative_risk"] = None
        out["Cancer"] = canc
    diab = out.get("Diabetes")
    if isinstance(diab, dict) and diab.get("score_range") and diab.get("risk_pct") is not None:
        diab = dict(diab)
        diab["risk_pct"] = None
        diab["shown_as"] = "interval"
        out["Diabetes"] = diab
    cvd = out.get("CVD")
    if isinstance(cvd, dict) and cvd.get("risk_pct") is not None and cvd.get("risk_band_label"):
        cvd = dict(cvd)
        cvd["risk_pct"] = None
        out["CVD"] = cvd
    return out


def check_serving_boundary(
    payload: Dict[str, Any],
    request: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, List[str]]:
    """
    Return (allow, violations). allow=True means payload may reach the glass.

    Checks the *incoming* payload (before sanitize) so exact/hero leaks are visible.
    """
    request = request or {}
    viol: List[str] = []
    raw = payload

    if _walk_exact(raw):
        viol.append("forbidden_exact")
    cid = raw.get("claim_id")
    if cid is not None and cid not in KNOWN_CLAIMS:
        viol.append("unknown_claim_id")
    if raw.get("health_age") is not None:
        viol.append("health_age_hero")
    canc = raw.get("Cancer") or {}
    if isinstance(canc, dict) and isinstance(canc.get("relative_risk"), (int, float)):
        viol.append("cancer_rr_hero")
    diab = raw.get("Diabetes") or {}
    if (
        isinstance(diab, dict)
        and diab.get("score_range")
        and isinstance(diab.get("risk_pct"), (int, float))
        and not diab.get("refused")
    ):
        viol.append("interval_collapsed")

    cvd = raw.get("CVD") or {}
    age = request.get("age")
    systolic = request.get("systolic", request.get("sbp"))
    race = request.get("race")
    prefer_pce = bool(request.get("prefer_pce"))
    mode = request.get("mode")
    allow_baseline = bool(request.get("study_allow_baseline"))

    if mode == "baseline" and not allow_baseline:
        viol.append("baseline_env")
    if systolic in (None, "", 0) and _cvd_numeric(cvd):
        viol.append("missing_sbp_numeric")
    if age is not None and age < 30 and _cvd_numeric(cvd):
        viol.append("under30_numeric")
    if age is not None and age > 79 and _cvd_numeric(cvd):
        viol.append("over79_numeric")
    if prefer_pce and race not in PCE_RACES:
        eq = str((cvd.get("equation") or "")).upper()
        if eq == "PCE" and _cvd_numeric(cvd):
            viol.append("unsupported_pce")

    return (len(viol) == 0), viol
