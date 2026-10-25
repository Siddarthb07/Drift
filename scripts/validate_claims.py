#!/usr/bin/env python3
"""CI: every claim_id used by the engine exists in claims.yaml with required fields."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from disclosure import load_claims  # noqa: E402

REQUIRED = {"title", "evidence_class", "display_policy", "validated_population", "source", "runtime"}
ENGINE_CLAIMS = {
    "prevent_ascvd",
    "pce_ascvd",
    "findrisc",
    "cancer_lifestyle_factors",
    "health_age_heuristic",
    "lifestyle_trajectory",
}


def main() -> int:
    claims = load_claims().get("claims") or {}
    missing = ENGINE_CLAIMS - set(claims)
    if missing:
        print("FAIL missing claims:", sorted(missing))
        return 1
    bad = []
    for cid in ENGINE_CLAIMS:
        c = claims[cid]
        lack = REQUIRED - set(c)
        if lack:
            bad.append((cid, sorted(lack)))
    if bad:
        print("FAIL incomplete claims:", bad)
        return 1
    # Honesty invariants
    if claims["health_age_heuristic"].get("display_policy") != "refuse":
        print("FAIL health_age must refuse in ledger")
        return 1
    if not claims["cancer_lifestyle_factors"].get("suppress_numeric"):
        print("FAIL cancer must suppress_numeric")
        return 1
    print(f"OK {len(ENGINE_CLAIMS)} claims validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
