"""Geographic / equation-preference regions for Drift.

All regions default to race-free AHA PREVENT for CVD computation.
Only `us_pce` may prefer ACC/AHA PCE when race ∈ {white, aa} and age ≥ 40
(or the user explicitly checks prefer_pce). Plain `us` stays PREVENT-first.
We do not invent unvalidated regional coefficients (SCORE2, WHO, etc.) —
those appear as honest coverage notes only.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

REGIONS: List[Dict[str, Any]] = [
    {
        "id": "global",
        "label": "Global",
        "short": "World — PREVENT default",
        "equation": "prevent",
        "prefer_pce": False,
        "note": "Race-free AHA PREVENT (sex-specific). Best default when no local equation is shipped.",
    },
    {
        "id": "us",
        "label": "United States",
        "short": "US — PREVENT (+ optional PCE)",
        "equation": "prevent",
        "prefer_pce": False,
        "note": "PREVENT by default. Optional PCE only for White / African American adults 40–79.",
    },
    {
        "id": "us_pce",
        "label": "United States (prefer PCE)",
        "short": "US — prefer PCE if eligible",
        "equation": "pce_when_eligible",
        "prefer_pce": True,
        "note": "Uses PCE when race is White/AA and age ≥ 40; otherwise PREVENT (no White fallback).",
    },
    {
        "id": "canada",
        "label": "Canada",
        "short": "Canada — PREVENT",
        "equation": "prevent",
        "prefer_pce": False,
        "note": "No Canadian CVD equation shipped here — PREVENT with coverage honesty.",
    },
    {
        "id": "uk_europe",
        "label": "United Kingdom & Western Europe",
        "short": "UK / W. Europe — PREVENT",
        "equation": "prevent",
        "prefer_pce": False,
        "note": "SCORE2 / QRISK not shipped in this build. Showing race-free PREVENT; FINDRISC is European-derived.",
    },
    {
        "id": "eastern_europe",
        "label": "Eastern Europe & Central Asia",
        "short": "E. Europe / Central Asia — PREVENT",
        "equation": "prevent",
        "prefer_pce": False,
        "note": "No SCORE2-OP / local CVD equation shipped — PREVENT with coverage honesty.",
    },
    {
        "id": "nordic",
        "label": "Nordic countries",
        "short": "Nordic — PREVENT",
        "equation": "prevent",
        "prefer_pce": False,
        "note": "SCORE2 not shipped. Race-free PREVENT; FINDRISC originated in Finland.",
    },
    {
        "id": "australia_nz",
        "label": "Australia & New Zealand",
        "short": "AU / NZ — PREVENT",
        "equation": "prevent",
        "prefer_pce": False,
        "note": "No AusCVD equation shipped — PREVENT with coverage honesty.",
    },
    {
        "id": "latin_america",
        "label": "Latin America",
        "short": "LatAm — PREVENT",
        "equation": "prevent",
        "prefer_pce": False,
        "note": "No region-specific CVD equation shipped — PREVENT (race-free).",
    },
    {
        "id": "caribbean",
        "label": "Caribbean",
        "short": "Caribbean — PREVENT",
        "equation": "prevent",
        "prefer_pce": False,
        "note": "PREVENT race-free. Local calibration not claimed.",
    },
    {
        "id": "south_asia",
        "label": "South Asia (India, Pakistan, Bangladesh, Sri Lanka…)",
        "short": "South Asia — PREVENT",
        "equation": "prevent",
        "prefer_pce": False,
        "note": "PREVENT is race-free (no White-PCE remapping for South Asian ethnicity).",
    },
    {
        "id": "east_asia",
        "label": "East Asia (China, Japan, Korea…)",
        "short": "East Asia — PREVENT",
        "equation": "prevent",
        "prefer_pce": False,
        "note": "PREVENT race-free. Local CV risk tools not shipped in this build.",
    },
    {
        "id": "southeast_asia",
        "label": "Southeast Asia",
        "short": "SE Asia — PREVENT",
        "equation": "prevent",
        "prefer_pce": False,
        "note": "PREVENT race-free default.",
    },
    {
        "id": "middle_east_nafrica",
        "label": "Middle East & North Africa",
        "short": "MENA — PREVENT",
        "equation": "prevent",
        "prefer_pce": False,
        "note": "PREVENT race-free default.",
    },
    {
        "id": "sub_saharan_africa",
        "label": "Sub-Saharan Africa",
        "short": "Sub-Saharan Africa — PREVENT",
        "equation": "prevent",
        "prefer_pce": False,
        "note": "PREVENT race-free. Local calibration not claimed.",
    },
    {
        "id": "pacific_islands",
        "label": "Pacific Islands",
        "short": "Pacific Islands — PREVENT",
        "equation": "prevent",
        "prefer_pce": False,
        "note": "PREVENT race-free default.",
    },
]

REGION_BY_ID: Dict[str, Dict[str, Any]] = {r["id"]: r for r in REGIONS}

# Legacy aliases
REGION_BY_ID["us_prevent"] = REGION_BY_ID["us"]
REGION_BY_ID["europe"] = REGION_BY_ID["uk_europe"]
REGION_BY_ID["mena"] = REGION_BY_ID["middle_east_nafrica"]
REGION_BY_ID["africa"] = REGION_BY_ID["sub_saharan_africa"]

GENDER_IDENTITY_OPTIONS = [
    ("", "Select"),
    ("male", "Male"),
    ("female", "Female"),
    ("nonbinary", "Non-binary"),
    ("another", "Another gender identity"),
    ("prefer_not", "Prefer not to say"),
]

EQUATION_SEX_OPTIONS = [
    ("", "Not set — we refuse a CVD number"),
    ("male", "Male"),
    ("female", "Female"),
]


def region_prefers_pce(region_id: Optional[str], prefer_pce_flag: bool = False) -> bool:
    rid = (region_id or "global").lower()
    meta = REGION_BY_ID.get(rid) or REGION_BY_ID["global"]
    return bool(prefer_pce_flag) or bool(meta.get("prefer_pce"))


def region_note(region_id: Optional[str]) -> str:
    rid = (region_id or "global").lower()
    meta = REGION_BY_ID.get(rid) or REGION_BY_ID["global"]
    return str(meta.get("note") or "")
