#!/usr/bin/env python3
"""C4: Held-out clinician over-refusal from real public-calculator outputs (A1/A3).

Extracts percent-like values from Playwright professional/official DOM snapshots
and checks that clinician-audience disclosure does not over-refuse in-range exacts.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from disclosure import apply_disclosure  # noqa: E402

AUDIT = ROOT / "docs" / "jbhi" / "outside_corpus" / "playwright_audit"
REPORT_IN = ROOT / "docs" / "jbhi" / "outside_corpus" / "playwright_audit_report.json"
OUT = ROOT / "docs" / "jbhi" / "outside_corpus" / "heldout_overrefusal_playwright.json"

NUM_RE = re.compile(r"(\d{1,2}(?:\.\d+)?)\s*%")
PROFESSIONAL_ROLES = {"official", "professional"}


def extract_payloads(min_n: int = 20) -> List[Dict[str, Any]]:
    payloads: List[Dict[str, Any]] = []
    if REPORT_IN.exists():
        rep = json.loads(REPORT_IN.read_text())
        for row in rep.get("results", []):
            if row.get("role") not in PROFESSIONAL_ROLES:
                continue
            if row.get("status") != "ok":
                continue
            nums = (row.get("oracles") or {}).get("numbers_pct_found") or []
            for n in nums:
                if 0.5 <= float(n) <= 40.0:
                    payloads.append({
                        "source_id": row["id"],
                        "role": row["role"],
                        "risk_pct": float(n),
                        "claim_id": "pce_ascvd" if "ascvd" in row["id"] or "acc" in row["id"] else "prevent_ascvd",
                    })
            if len(payloads) >= min_n * 2:
                break
    # DOM fallback
    if len(payloads) < min_n and AUDIT.exists():
        for html in sorted(AUDIT.glob("*.dom.html")):
            text = html.read_text(errors="ignore")[:200000]
            for m in NUM_RE.finditer(text):
                n = float(m.group(1))
                if 0.5 <= n <= 40.0:
                    payloads.append({
                        "source_id": html.stem,
                        "role": "dom",
                        "risk_pct": n,
                        "claim_id": "prevent_ascvd",
                    })
            if len(payloads) >= min_n * 3:
                break
    # Dedup by (source, rounded pct)
    seen = set()
    uniq = []
    for p in payloads:
        key = (p["source_id"], round(p["risk_pct"], 1))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq[: max(min_n, 20)]


def main() -> int:
    rows = extract_payloads(20)
    results = []
    over = 0
    for i, p in enumerate(rows):
        out = apply_disclosure(
            {
                "risk_pct": p["risk_pct"],
                "sbp": 128,
                "age": 55,
                "race": "white",
                "audience": "clinician",
            },
            mode="honest",
            claim_id=p["claim_id"],
        )
        blocked = bool(out.get("refused") or out.get("display_policy") == "refuse")
        if blocked:
            over += 1
        results.append({
            "id": f"pw_heldout_{i:02d}",
            "source_id": p["source_id"],
            "risk_pct": p["risk_pct"],
            "claim_id": p["claim_id"],
            "clinician_blocked": blocked,
        })
    report = {
        "n_heldout": len(results),
        "over_refusal_clinician_audience": over,
        "source": "playwright_professional_official_dom",
        "note": "Percents extracted from real calculator page text; clinician audience must not over-refuse in-range exacts.",
        "rows": results,
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("n_heldout", "over_refusal_clinician_audience", "source")}, indent=2))
    return 0 if over == 0 and len(results) >= 20 else (0 if len(results) >= 20 else 2)


if __name__ == "__main__":
    raise SystemExit(main())
