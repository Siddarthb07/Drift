#!/usr/bin/env python3
"""Fail if PAPER_DRAFT / tables.json disagree with committed facct JSON artifacts."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "docs" / "facct" / "PAPER_DRAFT.md"
TABLES = ROOT / "docs" / "facct" / "tables.json"
NHANES = ROOT / "docs" / "facct" / "nhanes_coverage_audit.json"
VIGNETTE = ROOT / "docs" / "facct" / "vignette_eval.json"
WC = ROOT / "study" / "warranted_certainty.json"


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def _vignette_means(vg: dict) -> tuple[float, float]:
    if "honest_mean" in vg and "baseline_mean" in vg:
        return float(vg["honest_mean"]), float(vg["baseline_mean"])
    per = vg["per_key"]
    h = sum(v["honest"] for v in per.values()) / len(per)
    b = sum(v["baseline"] for v in per.values()) / len(per)
    return h, b


def main() -> int:
    nh = json.loads(NHANES.read_text())
    vg = json.loads(VIGNETTE.read_text())
    tables = json.loads(TABLES.read_text())
    paper = PAPER.read_text()
    wc = json.loads(WC.read_text())

    n = nh["n_analyzed"]
    if tables["table2_nhanes"]["n"] != n:
        fail(f"tables.json n={tables['table2_nhanes']['n']} != nhanes n_analyzed={n}")
    if tables["table2_nhanes"]["misattributed_equation_count"] != nh["overall"]["misattributed_equation_count"]:
        fail("tables.json misattributed_equation_count mismatch")

    for race in ("hispanic", "asian_nhanes", "multiracial"):
        expected = nh["by_race"][race]["legacy"]["misattributed_equation_count"]
        got = tables["table2_nhanes"]["by_race_misattributed_n"].get(race)
        if got != expected:
            fail(f"tables misattributed {race}: {got} != {expected}")

    if not re.search(rf"\bn[= ]*{n}\b", paper):
        fail(f"PAPER_DRAFT.md missing n={n}")

    for stale in ("n=2500", "n=4000", "WTMEC4YR", "**405***", "**228***", "**77***", "(see JSON)"):
        if stale in paper:
            fail(f"PAPER_DRAFT.md still contains stale token {stale!r}")

    # Burden counts must appear as exact integers from JSON
    for race, label in (
        ("hispanic", "Hispanic"),
        ("asian_nhanes", "Asian"),
        ("multiracial", "Multiracial"),
    ):
        count = nh["by_race"][race]["legacy"]["misattributed_equation_count"]
        if str(count) not in paper:
            fail(f"PAPER_DRAFT.md missing misattributed count {count} for {label}")

    if wc.get("locked") is False:
        if re.search(r"Instrument frozen", paper) and "not locked" not in paper.lower() and "locked:false" not in paper.replace(" ", ""):
            fail("PAPER claims Instrument frozen while warranted_certainty.json locked:false without clarifying")

    hm, bm = _vignette_means(vg)
    if abs(tables["table3_vignette"]["honest_mean"] - hm) > 0.01:
        fail("table3 honest_mean mismatch vs vignette_eval.json")
    if abs(tables["table3_vignette"]["baseline_mean"] - bm) > 0.01:
        fail("table3 baseline_mean mismatch vs vignette_eval.json")

    if "STUDY_ALLOW_BASELINE=1" not in (ROOT / "ARTIFACT.md").read_text():
        fail("ARTIFACT.md missing STUDY_ALLOW_BASELINE=1")

    print(json.dumps({"ok": True, "n_analyzed": n, "misattributed": nh["overall"]["misattributed_equation_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
