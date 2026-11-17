"""Load-bearing disclosure gates for mutation testing (subset of disclosure.py)."""
from typing import Any, Dict, Optional, List, Tuple

CVD_BANDS = [
    (0.0, 5.0, "<5%", "Low"),
    (5.0, 7.5, "5–<7.5%", "Borderline"),
    (7.5, 20.0, "7.5–20%", "Intermediate"),
    (20.0, 100.0, "≥20%", "High"),
]

class DisclosureError(Exception):
    pass

def band_for(value: float, bands=CVD_BANDS) -> Dict[str, str]:
    for lo, hi, label, category in bands:
        if lo <= value < hi or (hi >= 100 and value >= lo):
            return {"label": label, "category": category}
    return {"label": "Unknown", "category": "Unknown"}

def check_age_bounds(age, age_min=None, age_max=None) -> Optional[str]:
    if age_min is None and age_max is None:
        return None
    if age is None:
        return "Claim requires age; missing"
    if age_min is not None and float(age) < float(age_min):
        return f"Claim requires age ≥ {age_min}"
    if age_max is not None and float(age) > float(age_max):
        return f"Claim requires age ≤ {age_max}"
    return None

def check_race_in(race, allowed) -> Optional[str]:
    r = str(race or "").lower()
    allow = [str(x).lower() for x in allowed]
    if not r:
        return "Claim requires race; missing"
    if r not in allow:
        return f"Claim requires race in {allow}; got {r}"
    return None

def refuse_white_fallback(claim_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    if claim_id == "pce_ascvd" and out.get("legacy_white_fallback"):
        out["refused"] = True
        out["gate"] = "prohibited_use"
        out["note"] = "White-equation fallback is prohibited for PCE"
        out["risk_pct"] = None
        out["display_policy"] = "refuse"
    return out

def apply_consumer_band(payload: Dict[str, Any], *, audience: str = "consumer") -> Dict[str, Any]:
    out = dict(payload)
    if audience != "consumer":
        return out
    if out.get("refused") or out.get("display_policy") == "refuse":
        out["risk_pct"] = None
        return out
    if out.get("risk_pct") is None:
        return out
    pct = float(out["risk_pct"])
    b = band_for(pct)
    out["risk_band_label"] = b["label"]
    out["risk_pct_exact"] = pct
    out["risk_pct"] = None
    out["shown_as"] = "band"
    out["display_policy"] = "band"
    return out

_PUBLIC_STRIP_KEYS = ("risk_pct_exact", "relative_risk_exact", "_audit_exact")

def public_view(payload: Any) -> Any:
    if isinstance(payload, dict):
        out = {}
        for k, v in payload.items():
            if k in _PUBLIC_STRIP_KEYS:
                continue
            out[k] = public_view(v)
        return out
    if isinstance(payload, list):
        return [public_view(x) for x in payload]
    return payload

def enforce(payload: Dict[str, Any], *, claim_id: str, audience: str = "consumer",
            age_min=40, age_max=79, race_allowed=None) -> Dict[str, Any]:
    out = dict(payload)
    out = refuse_white_fallback(claim_id, out)
    if out.get("refused"):
        return out
    if race_allowed is not None:
        msg = check_race_in(out.get("race"), race_allowed)
        if msg:
            out.update(refused=True, display_policy="refuse", risk_pct=None, note=msg, gate="claim_requires")
            return out
    msg = check_age_bounds(out.get("age"), age_min, age_max)
    if msg:
        out.update(refused=True, display_policy="refuse", risk_pct=None, note=msg, gate="claim_requires")
        return out
    if audience == "consumer":
        out = apply_consumer_band(out, audience=audience)
    return out
