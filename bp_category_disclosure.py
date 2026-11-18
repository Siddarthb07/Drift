"""
Blood-pressure category disclosure — second independent claim domain.

Educational ACC/AHA 2017 office BP categories. Not PREVENT, not PCE, not a
CVD risk equation. Demonstrates that executable disclosure contracts port to a
new clinical-guideline domain with YAML claims + apply_disclosure + public_view.

Serving path: compute_bp_category → apply_disclosure → serve_bp_disclosure
(public_view + domain false-precision strip).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from disclosure import apply_disclosure, public_view

CLAIM_CATEGORY = "bp_category_acc2017"
CLAIM_FACTORS = "bp_modifiable_factors"
CLAIM_HOME_AVG = "bp_home_average_heuristic"

# Keys retained for offline audit only — stripped before serving.
_DOMAIN_EXACT_KEYS = (
    "sbp_mmhg_exact",
    "dbp_mmhg_exact",
    "home_mean_sbp_exact",
    "home_mean_dbp_exact",
)

BP_LIFESTYLE_FACTORS: List[Dict[str, str]] = [
    {"id": "sodium", "label": "Excess dietary sodium"},
    {"id": "weight", "label": "Elevated body weight"},
    {"id": "activity", "label": "Insufficient physical activity"},
    {"id": "alcohol", "label": "Excessive alcohol intake"},
    {"id": "diet", "label": "Low potassium / DASH-style dietary pattern not met"},
]


def classify_acc2017(sbp: float, dbp: float) -> Dict[str, str]:
    """
    ACC/AHA 2017 adult BP categories (office measurement context).
    Crisis checked first; otherwise highest applicable stage wins.
    """
    if sbp > 180 or dbp > 120:
        return {
            "category": "Hypertensive crisis",
            "code": "crisis",
            "note": "Seek emergency care guidance — educational label only.",
        }
    if sbp >= 140 or dbp >= 90:
        return {"category": "Stage 2 hypertension", "code": "stage2", "note": ""}
    if sbp >= 130 or dbp >= 80:
        return {"category": "Stage 1 hypertension", "code": "stage1", "note": ""}
    if sbp >= 120 and dbp < 80:
        return {"category": "Elevated", "code": "elevated", "note": ""}
    return {"category": "Normal", "code": "normal", "note": ""}


def _parse_mmhg(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_bp_category(
    user: Dict[str, Any],
    *,
    mode: str = "honest",
) -> Dict[str, Any]:
    """
    Classify office BP → claim-ledger disclosure payload.

    Fail-closed on missing SBP/DBP (no silent 120/80). False-precision raw
    floats kept only as *_exact audit fields.
    """
    sbp = _parse_mmhg(user.get("systolic") if "systolic" in user else user.get("sbp"))
    dbp = _parse_mmhg(user.get("diastolic") if "diastolic" in user else user.get("dbp"))
    age = user.get("age")

    raw: Dict[str, Any] = {
        "equation": "ACC/AHA 2017 BP category",
        "claim_domain": "blood_pressure_category",
        "age": age,
        "factors": list(BP_LIFESTYLE_FACTORS),
    }

    if sbp is None or dbp is None:
        raw.update(
            {
                "refused": True,
                "gate": "missing_bp",
                "note": (
                    "Office BP category requires measured systolic and diastolic. "
                    "Missing values are not imputed (prohibited: silent_missing_bp_imputation)."
                ),
                "bp_category": None,
                "bp_category_code": None,
                "sbp_mmhg": None,
                "dbp_mmhg": None,
            }
        )
        return apply_disclosure(raw, mode=mode, claim_id=CLAIM_CATEGORY)

    # Audit-only false precision; public path rounds to integer mmHg.
    raw["sbp_mmhg_exact"] = sbp
    raw["dbp_mmhg_exact"] = dbp
    raw["sbp_mmhg"] = int(round(sbp))
    raw["dbp_mmhg"] = int(round(dbp))

    cat = classify_acc2017(sbp, dbp)
    raw["bp_category"] = cat["category"]
    raw["bp_category_code"] = cat["code"]
    if cat.get("note"):
        raw["note"] = cat["note"]

    return apply_disclosure(raw, mode=mode, claim_id=CLAIM_CATEGORY)


def compute_bp_modifiable_factors(*, mode: str = "honest") -> Dict[str, Any]:
    """Factors-only educational list — no compounded BP risk product."""
    raw = {
        "factors": list(BP_LIFESTYLE_FACTORS),
        "relative_risk": None,
        "note": "Factor list only — no combined relative-risk or absolute probability.",
    }
    return apply_disclosure(raw, mode=mode, claim_id=CLAIM_FACTORS)


def compute_bp_home_average_refused(
    readings: Optional[List[Dict[str, Any]]] = None,
    *,
    mode: str = "honest",
) -> Dict[str, Any]:
    """
    Home-average heuristic is ledger-refused (no protocol provenance).
    Even if readings exist, numeric mean is not shown under this claim_id.
    """
    raw: Dict[str, Any] = {
        "readings_n": len(readings or []),
        "health_age": None,
    }
    if readings:
        sbps = [_parse_mmhg(r.get("sbp") or r.get("systolic")) for r in readings]
        dbps = [_parse_mmhg(r.get("dbp") or r.get("diastolic")) for r in readings]
        sbps_ok = [x for x in sbps if x is not None]
        dbps_ok = [x for x in dbps if x is not None]
        if sbps_ok and dbps_ok:
            # Would-be false precision — retained only as audit fields, then refused.
            raw["home_mean_sbp_exact"] = sum(sbps_ok) / len(sbps_ok)
            raw["home_mean_dbp_exact"] = sum(dbps_ok) / len(dbps_ok)
    return apply_disclosure(raw, mode=mode, claim_id=CLAIM_HOME_AVG)


def _strip_domain_exact(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            k: _strip_domain_exact(v)
            for k, v in payload.items()
            if k not in _DOMAIN_EXACT_KEYS
        }
    if isinstance(payload, list):
        return [_strip_domain_exact(x) for x in payload]
    return payload


def serve_bp_disclosure(
    user: Dict[str, Any],
    *,
    mode: str = "honest",
    include_factors: bool = True,
) -> Dict[str, Any]:
    """
    Public serving path for the BP domain:
    compute → ledger → strip domain exact fields → public_view.
    """
    payload: Dict[str, Any] = {
        "BP": compute_bp_category(user, mode=mode),
        "BP_home_average": compute_bp_home_average_refused(mode=mode),
    }
    if include_factors:
        payload["BP_factors"] = compute_bp_modifiable_factors(mode=mode)
    return public_view(_strip_domain_exact(payload))


def demo_payload() -> Dict[str, Any]:
    """Minimal example for scripts / docs."""
    return serve_bp_disclosure(
        {"age": 52, "systolic": 128.47, "diastolic": 82.13},
        mode="honest",
    )


if __name__ == "__main__":
    import json

    print(json.dumps(demo_payload(), indent=2))
