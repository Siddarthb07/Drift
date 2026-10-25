#!/usr/bin/env python3
"""CI: claim ledger is complete; every claim_id emitted in source exists; fail-closed invariants."""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from disclosure import DisclosureError, load_claims  # noqa: E402

REQUIRED = {"title", "evidence_class", "display_policy", "validated_population", "source", "runtime"}
SOURCE_FILES = [
    ROOT / "risk_engine.py",
    ROOT / "legacy_baseline.py",
    ROOT / "disclosure.py",
    ROOT / "app_v5.py",
]


def _claim_ids_in_source() -> set[str]:
    found: set[str] = set()
    pat = re.compile(r'claim_id\s*=\s*["\']([a-z0-9_]+)["\']')
    for path in SOURCE_FILES:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        found.update(pat.findall(text))
        # dict literals in apply_disclosure maps
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if re.fullmatch(r"[a-z][a-z0-9_]+", node.value) and "claim" in text:
                    pass  # too broad; regex above is enough
    return found


def main() -> int:
    try:
        claims = load_claims(refresh=True).get("claims") or {}
    except DisclosureError as e:
        print("FAIL ledger:", e)
        return 1

    emitted = _claim_ids_in_source()
    # Always require core set
    emitted |= {
        "prevent_ascvd", "pce_ascvd", "findrisc", "cancer_lifestyle_factors",
        "health_age_heuristic", "lifestyle_trajectory", "legacy_baseline",
    }
    missing = emitted - set(claims)
    if missing:
        print("FAIL missing claims for emitted IDs:", sorted(missing))
        return 1

    bad = []
    for cid, c in claims.items():
        lack = REQUIRED - set(c)
        if lack:
            bad.append((cid, sorted(lack)))
    if bad:
        print("FAIL incomplete claims:", bad)
        return 1

    if claims["health_age_heuristic"].get("display_policy") != "refuse":
        print("FAIL health_age must refuse in ledger")
        return 1
    if not claims["cancer_lifestyle_factors"].get("suppress_numeric"):
        print("FAIL cancer must suppress_numeric")
        return 1
    if claims["legacy_baseline"].get("runtime") != "baseline_study_arm_only":
        print("FAIL legacy_baseline must be study-arm-only")
        return 1

    print(f"OK {len(claims)} claims; emitted_ids={sorted(emitted)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
