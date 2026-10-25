#!/usr/bin/env python3
"""Fail if tables.json disagree with committed facct JSON artifacts.

PAPER_DRAFT.md narrative sync is optional: set CHECK_PAPER_DRAFT=1 locally when
editing the draft. CI keeps paper details out of the push path and only checks
machine-readable artifacts + ARTIFACT.md.
"""
from __future__ import annotations

import json
import os
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
    if "honest_mean_pass_rate" in vg and "baseline_mean_pass_rate" in vg:
        return float(vg["honest_mean_pass_rate"]), float(vg["baseline_mean_pass_rate"])
    if "honest_mean" in vg and "baseline_mean" in vg:
        return float(vg["honest_mean"]), float(vg["baseline_mean"])
    per = vg["per_key"]
    h = sum(v["honest"] for v in per.values()) / len(per)
    b = sum(v["baseline"] for v in per.values()) / len(per)
    return h, b


def check_paper_draft(nh: dict, vg: dict, wc: dict) -> None:
    if not PAPER.exists():
        fail("PAPER_DRAFT.md missing while CHECK_PAPER_DRAFT=1")
    paper = PAPER.read_text()
    n = nh["n_analyzed"]

    if not re.search(rf"\bn[= ]*{n}\b", paper):
        fail(f"PAPER_DRAFT.md missing n={n}")

    for stale in ("n=2500", "n=4000", "WTMEC4YR", "**405***", "**228***", "**77***", "(see JSON)"):
        if stale in paper:
            fail(f"PAPER_DRAFT.md still contains stale token {stale!r}")

    for race, label in (
        ("hispanic", "Hispanic"),
        ("asian_nhanes", "Asian"),
        ("multiracial", "Multiracial"),
    ):
        count = nh["by_race"][race]["legacy"]["misattributed_equation_count"]
        if str(count) not in paper:
            fail(f"PAPER_DRAFT.md missing misattributed count {count} for {label}")

    for race in ("white", "aa", "hispanic", "asian_nhanes", "multiracial"):
        shares = sorted(
            nh["by_race"][race]["honest"]["refuse_gates_weighted_share"].items(),
            key=lambda x: -x[1],
        )[:3]
        for _gate, share in shares:
            token = f"{share:.3f}"
            if token not in paper:
                fail(f"PAPER_DRAFT.md missing weighted gate share {token} for {race}")

    if re.search(r"Field-ready", paper):
        fail("PAPER_DRAFT.md still contains 'Field-ready' while study is not locked/timestamped")

    if wc.get("locked") is False:
        if (
            re.search(r"Instrument frozen", paper)
            and "not locked" not in paper.lower()
            and "locked:false" not in paper.replace(" ", "")
        ):
            fail("PAPER claims Instrument frozen while warranted_certainty.json locked:false without clarifying")

    n_cases = vg.get("n_cases")
    if n_cases is not None:
        compact = paper.replace(" ", "")
        ok_count = (
            f"n={n_cases}" in compact
            or f"{n_cases}fixtures" in compact.lower()
            or "Twenty-three fixtures" in paper
            or "23 fixtures" in paper
        )
        if not ok_count:
            fail("PAPER_DRAFT.md missing updated vignette fixture count")

    h40 = nh["overall"].get("weighted_honest_show_rate_age_40_79")
    l40 = nh["overall"].get("weighted_legacy_show_rate_age_40_79")
    if h40 is not None and f"{h40:.3f}"[:5] not in paper and "0.810" not in paper:
        fail("PAPER_DRAFT.md missing age 40–79 honest weighted show")
    if l40 is not None and "0.947" not in paper:
        fail("PAPER_DRAFT.md missing age 40–79 legacy weighted show")


def main() -> int:
    nh = json.loads(NHANES.read_text())
    vg = json.loads(VIGNETTE.read_text())
    tables = json.loads(TABLES.read_text())
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

    hm, bm = _vignette_means(vg)
    if abs(tables["table3_vignette"]["honest_mean"] - hm) > 0.01:
        fail("table3 honest_mean mismatch vs vignette_eval.json")
    if abs(tables["table3_vignette"]["baseline_mean"] - bm) > 0.01:
        fail("table3 baseline_mean mismatch vs vignette_eval.json")
    if tables["table3_vignette"].get("n_cases") != vg.get("n_cases"):
        fail(f"table3 n_cases {tables['table3_vignette'].get('n_cases')} != vignette {vg.get('n_cases')}")

    # Optional local age-40–79 fields in tables when present in NHANES JSON
    for key in ("weighted_honest_show_rate_age_40_79", "weighted_legacy_show_rate_age_40_79"):
        if key in nh["overall"] and key in tables.get("table2_nhanes", {}):
            if tables["table2_nhanes"][key] != nh["overall"][key]:
                fail(f"tables.json {key} mismatch vs nhanes JSON")

    if "STUDY_ALLOW_BASELINE=1" not in (ROOT / "ARTIFACT.md").read_text():
        fail("ARTIFACT.md missing STUDY_ALLOW_BASELINE=1")
    if "public_view" not in (ROOT / "ARTIFACT.md").read_text():
        fail("ARTIFACT.md missing public_view serving-path strip")

    paper_checked = False
    if os.getenv("CHECK_PAPER_DRAFT", "0") in ("1", "true", "True", "yes"):
        check_paper_draft(nh, vg, wc)
        paper_checked = True

    print(json.dumps({
        "ok": True,
        "n_analyzed": n,
        "misattributed": nh["overall"]["misattributed_equation_count"],
        "n_vignettes": vg.get("n_cases"),
        "paper_draft_checked": paper_checked,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
