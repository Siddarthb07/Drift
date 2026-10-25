"""
Evidence-contingent disclosure engine.

Maps calculator outputs + claim ledger rules → display policy:
  number | band | qualitative | refuse | factors_only

Fail-closed: missing YAML, missing PyYAML, or unknown claim_id raises.
Honest mode: bands, provenance, no silent defaults, no health-age hero.
Baseline mode: legacy score-first UI for the FAccT vignette study only.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None

CLAIMS_PATH = Path(__file__).parent / "claims.yaml"
AUDIT_LOG_PATH = Path(os.getenv("DRIFT_AUDIT_LOG", "audit_display.jsonl"))

CVD_BANDS = [
    (0.0, 5.0, "<5%", "Low"),
    (5.0, 7.5, "5–7.5%", "Borderline"),
    (7.5, 20.0, "7.5–20%", "Intermediate"),
    (20.0, 100.0, "≥20%", "High"),
]
DIAB_BANDS = [
    (0.0, 5.0, "<5%", "Low"),
    (5.0, 17.0, "5–17%", "Slightly elevated"),
    (17.0, 33.0, "17–33%", "Moderate"),
    (33.0, 50.0, "33–50%", "High"),
    (50.0, 100.0, ">50%", "Very high"),
]


_CLAIMS_CACHE: Optional[Dict[str, Any]] = None


class DisclosureError(RuntimeError):
    """Fail-closed contract violation."""


def load_claims(*, refresh: bool = False) -> Dict[str, Any]:
    global _CLAIMS_CACHE
    if _CLAIMS_CACHE is not None and not refresh:
        return _CLAIMS_CACHE
    if yaml is None:
        raise DisclosureError("PyYAML is required for claim-ledger enforcement")
    if not CLAIMS_PATH.exists():
        raise DisclosureError(f"Missing claim ledger: {CLAIMS_PATH}")
    with open(CLAIMS_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data.get("claims"), dict) or not data["claims"]:
        raise DisclosureError("claims.yaml has no claims map")
    _CLAIMS_CACHE = data
    return _CLAIMS_CACHE


def _band_for(value: float, bands) -> Dict[str, str]:
    for lo, hi, label, category in bands:
        if lo <= value < hi or (hi >= 100 and value >= lo):
            return {"label": label, "category": category}
    return {"label": "Unknown", "category": "Unknown"}


def _check_requires(claim: Dict[str, Any], raw: Dict[str, Any]) -> Optional[str]:
    """Return refusal note if requires predicates fail; else None. Fail-closed on missing fields."""
    req = claim.get("requires") or {}
    if not req:
        return None
    race = str(raw.get("race") or raw.get("mapped_race") or "").lower()
    if "race_in" in req:
        allowed = [str(x).lower() for x in req["race_in"]]
        if not race:
            return "Claim requires race; missing"
        if race not in allowed:
            return f"Claim requires race in {allowed}; got {race}"
    age = raw.get("age")
    if "age_min" in req or "age_max" in req:
        if age is None:
            return "Claim requires age; missing"
        if "age_min" in req and float(age) < float(req["age_min"]):
            return f"Claim requires age ≥ {req['age_min']}"
        if "age_max" in req and float(age) > float(req["age_max"]):
            return f"Claim requires age ≤ {req['age_max']}"
    return None


def apply_disclosure(
    raw: Dict[str, Any],
    *,
    mode: str = "honest",
    claim_id: str,
) -> Dict[str, Any]:
    """Attach claim metadata and enforce display policy. Fail-closed on unknown claim_id."""
    claims = load_claims().get("claims", {})
    if claim_id not in claims:
        raise DisclosureError(f"Unknown claim_id: {claim_id}")
    claim = claims[claim_id]
    out = dict(raw)
    out["claim_id"] = claim_id
    out["evidence_class"] = claim["evidence_class"]
    out["validated_population"] = claim["validated_population"]
    out["prohibited_uses"] = list(claim.get("prohibited_uses") or [])
    policy = claim["display_policy"]
    if policy not in ("band", "refuse", "factors_only", "qualitative", "number"):
        raise DisclosureError(f"Invalid display_policy for {claim_id}: {policy}")
    out["display_policy"] = policy

    if mode == "baseline":
        if os.getenv("STUDY_ALLOW_BASELINE") != "1":
            raise DisclosureError("baseline mode requires STUDY_ALLOW_BASELINE=1")
        out["ui_mode"] = "baseline"
        return out

    out["ui_mode"] = "honest"
    # Predicate checks (e.g. PCE race coverage)
    pred_fail = _check_requires(claim, out)
    if pred_fail and not out.get("refused"):
        out["refused"] = True
        out["gate"] = out.get("gate") or "claim_requires"
        out["note"] = pred_fail
        out["risk_pct"] = None
        out["relative_risk"] = None
        out["display_policy"] = "refuse"
        return out

    policy = out["display_policy"]

    if out.get("refused") or out.get("gate"):
        out["display_policy"] = "refuse"
        out.pop("risk_pct", None)
        out.pop("relative_risk", None)
        out.pop("risk_pct_exact", None)
        return out

    if policy == "refuse" or claim.get("suppress_numeric"):
        out["risk_pct"] = None
        out["relative_risk"] = None
        out.pop("risk_pct_exact", None)
        out["display_policy"] = "refuse" if policy == "refuse" else policy
        if claim.get("suppress_numeric"):
            out["shown_as"] = "factors" if policy == "factors_only" else "suppressed"
        return out

    if policy == "band" and out.get("risk_pct") is not None:
        pct = float(out["risk_pct"])
        bands = DIAB_BANDS if claim_id == "findrisc" else CVD_BANDS
        b = _band_for(pct, bands)
        out["risk_band_label"] = b["label"]
        out["risk_category"] = out.get("risk_category") or b["category"]
        # Keep exact only for audit/tests — templates must not render risk_pct_exact
        out["risk_pct_exact"] = pct
        out["risk_pct"] = None
        out["shown_as"] = "band"

    if policy == "factors_only":
        out["relative_risk"] = None
        out["risk_pct"] = None
        out.pop("risk_pct_exact", None)
        out["shown_as"] = "factors"
        out.setdefault(
            "note",
            "Lifestyle factors listed individually. No combined relative-risk product is shown.",
        )

    if policy == "qualitative":
        out["risk_pct"] = None
        out["health_age"] = None
        out.pop("risk_pct_exact", None)
        out["shown_as"] = "qualitative"

    return out


def input_hash(payload: Dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def append_audit(
    *,
    username: str,
    claim_id: str,
    decision: str,
    evidence_class: str,
    inputs: Dict[str, Any],
    mode: str,
    equation: Optional[str] = None,
) -> None:
    if os.getenv("DRIFT_AUDIT", "1") in ("0", "false", "False"):
        return
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "user_hash": hashlib.sha256(username.encode()).hexdigest()[:12],
        "claim_id": claim_id,
        "decision": decision,
        "evidence_class": evidence_class,
        "equation": equation,
        "mode": mode,
        "input_hash": input_hash(inputs),
    }
    with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def lifestyle_trajectory(daily_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Replace health-age hero with modifiable-habit summary."""
    if not daily_rows:
        return {
            "label": "Insufficient lifestyle data",
            "detail": "Log sleep, steps, and stress to see a trajectory.",
            "color": "gray",
            "habits_active": 0,
            "habits_total": 6,
        }
    n = len(daily_rows)

    def mean(key):
        vals = [r.get(key) for r in daily_rows if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    avg_sleep = mean("sleep")
    avg_steps = mean("steps")
    avg_stress = mean("stress_level")
    avg_veg = mean("veg_servings")
    avg_fruit = mean("fruit_servings")
    avg_active = mean("active_minutes")

    checks = [
        avg_sleep is not None and 7 <= avg_sleep <= 9,
        avg_steps is not None and avg_steps >= 7500,
        avg_stress is not None and avg_stress <= 5,
        avg_veg is not None and avg_veg >= 2,
        avg_fruit is not None and avg_fruit >= 1,
        avg_active is not None and avg_active >= 20,
    ]
    active = sum(1 for c in checks if c)
    trend = "stable"
    if n >= 10 and avg_steps:
        recent = [r.get("steps") for r in daily_rows[:7] if r.get("steps") is not None]
        older = [r.get("steps") for r in daily_rows[7:14] if r.get("steps") is not None]
        if recent and older:
            r_m, o_m = sum(recent) / len(recent), sum(older) / len(older)
            if r_m > o_m * 1.1:
                trend = "improving"
            elif r_m < o_m * 0.9:
                trend = "worsening"

    color = "green" if active >= 4 else ("yellow" if active >= 2 else "orange")
    return {
        "label": f"{active} of 6 protective habits active",
        "detail": f"{n}-day window · trajectory: {trend}",
        "color": color,
        "habits_active": active,
        "habits_total": 6,
        "trend": trend,
        "note": "Habit summary only — not a biological age or clinical measurement.",
    }
