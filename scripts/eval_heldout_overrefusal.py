#!/usr/bin/env python3
"""Held-out over-refusal evaluation for audience predicate.

Training/tuning used the original 37 mapped outside-corpus outputs.
This script builds a disjoint held-out set of clinician-style exact-percent
payloads (synthetic but never seen by the predicate design loop) and reports
over-refusal under audience=clinician vs consumer.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("STUDY_ALLOW_BASELINE", "1")

from disclosure import apply_disclosure, public_view, DisclosureError, load_claims  # noqa: E402

OUT = ROOT / "docs" / "jbhi" / "outside_corpus" / "heldout_overrefusal.json"
load_claims(refresh=True)

# Held-out clinician calculator-style payloads (disjoint IDs / profiles from outside corpus)
HELDOUT = []
for i, (age, sex, race, risk) in enumerate([
    (42, "female", "white", 3.2), (48, "male", "aa", 7.1), (61, "female", "white", 14.8),
    (70, "male", "aa", 22.4), (55, "female", "aa", 5.5), (58, "male", "white", 9.9),
    (45, "female", "white", 2.8), (66, "male", "aa", 18.2), (52, "female", "aa", 6.4),
    (63, "male", "white", 11.5), (47, "female", "white", 4.1), (72, "male", "aa", 25.0),
    (50, "female", "aa", 8.0), (57, "male", "white", 10.2), (68, "female", "white", 16.7),
    (44, "male", "aa", 5.9), (59, "female", "aa", 12.3), (53, "male", "white", 7.7),
    (64, "female", "white", 13.1), (71, "male", "aa", 19.8),
]):
    HELDOUT.append({
        "id": f"heldout_clin_{i:02d}",
        "claim_id": "pce_ascvd",
        "raw": {"risk_pct": risk, "sbp": 128, "age": age, "race": race, "audience": "clinician"},
        "intended_use_valid_display": True,
    })


def blocked(out, pub) -> bool:
    if out.get("refused") or out.get("display_policy") == "refuse":
        return True
    if out.get("shown_as") == "band" and pub.get("risk_pct") is None:
        return True
    return False


def main() -> int:
    rows = []
    over_clin = over_cons = 0
    for c in HELDOUT:
        raw_c = dict(c["raw"])
        raw_s = dict(c["raw"]); raw_s["audience"] = "consumer"
        try:
            out_c = apply_disclosure(raw_c, mode="honest", claim_id=c["claim_id"])
            pub_c = public_view(out_c)
            b_c = blocked(out_c, pub_c)
        except DisclosureError:
            b_c = True
        try:
            out_s = apply_disclosure(raw_s, mode="honest", claim_id=c["claim_id"])
            pub_s = public_view(out_s)
            b_s = blocked(out_s, pub_s)
        except DisclosureError:
            b_s = True
        if b_c and c["intended_use_valid_display"]:
            over_clin += 1
        if b_s and c["intended_use_valid_display"]:
            over_cons += 1
        rows.append({"id": c["id"], "clinician_blocked": b_c, "consumer_blocked": b_s})

    report = {
        "n_heldout": len(HELDOUT),
        "over_refusal_clinician_audience": over_clin,
        "over_refusal_consumer_audience": over_cons,
        "note": "Held-out clinician-style exact percents never used to fit audience predicate.",
        "rows": rows,
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in report if k != "rows"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
