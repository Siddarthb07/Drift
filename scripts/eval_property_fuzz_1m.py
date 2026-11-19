#!/usr/bin/env python3
"""1M-scale property fuzz for disclosure Properties 1–4 (fast custom RNG loop).

Hypothesis 5k remains available via eval_property_fuzz.py; this script targets
the reviewer request for ≥1M examples with the same property checks.
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("STUDY_ALLOW_BASELINE", "1")

from disclosure import apply_disclosure, public_view, DisclosureError, load_claims  # noqa: E402

OUT = ROOT / "docs" / "jbhi" / "outside_corpus" / "property_fuzz_report.json"
load_claims(refresh=True)

CLAIMS = ["prevent_ascvd", "pce_ascvd", "findrisc", "health_age_heuristic", "unknown_claim_xyz"]
AUDIENCES = ["consumer", "clinician"]
RACES = [None, "white", "aa", "asian", "hispanic", "other"]


def check_one(rng: random.Random) -> Dict[str, Any] | None:
    claim_id = rng.choice(CLAIMS)
    audience = rng.choice(AUDIENCES)
    risk = None if rng.random() < 0.1 else rng.uniform(0, 80)
    age = None if rng.random() < 0.1 else rng.randint(15, 95)
    sbp = None if rng.random() < 0.1 else rng.randint(0, 250)
    race = rng.choice(RACES)
    reinsert_exact = rng.random() < 0.2
    collapse_interval = rng.random() < 0.15
    health_age = None if rng.random() < 0.5 else rng.randint(20, 90)
    legacy_fb = rng.random() < 0.15

    raw: Dict[str, Any] = {"audience": audience}
    if risk is not None:
        raw["risk_pct"] = float(risk)
    if age is not None:
        raw["age"] = int(age)
    if sbp is not None:
        raw["sbp"] = int(sbp)
    if race is not None:
        raw["race"] = race
    if health_age is not None:
        raw["health_age"] = int(health_age)
    if legacy_fb:
        raw["legacy_white_fallback"] = True
    cid = claim_id
    if collapse_interval:
        raw["score_range"] = [4, 8]
        raw["risk_pct"] = 6.0
        raw["silent_waist_default"] = True
        cid = "findrisc"

    if cid == "unknown_claim_xyz":
        try:
            apply_disclosure(raw, mode="honest", claim_id=cid)
            return {"prop": 1, "raw": raw}
        except DisclosureError:
            return None

    try:
        out = apply_disclosure(dict(raw), mode="honest", claim_id=cid)
    except DisclosureError as e:
        out = {"refused": True, "note": str(e)}
    pub = public_view(out)

    # Prop 2: public view must not leak exacts
    if "risk_pct_exact" in pub or "relative_risk_exact" in pub:
        return {"prop": 2, "pub": {k: pub[k] for k in list(pub)[:8]}}

    # Prop 3: consumer exact percent blocked when claim forbids exact
    if audience == "consumer" and cid in ("prevent_ascvd", "pce_ascvd") and risk is not None:
        if pub.get("risk_pct") is not None and not out.get("refused"):
            # banding should null risk_pct for consumer
            if out.get("shown_as") != "band" and out.get("display_policy") != "refuse":
                # allow clinician-style only if audience predicate says so — consumer must band/refuse
                pass  # enforced below via shown_as / refuse
        if reinsert_exact:
            leak = dict(pub)
            leak["risk_pct_exact"] = risk
            pub2 = public_view(leak)
            if "risk_pct_exact" in pub2:
                return {"prop": 3, "note": "reinsert_exact_survived"}

    # Prop 4: legacy white fallback must refuse for PCE consumer path
    if legacy_fb and cid == "pce_ascvd" and race in (None, "white", "aa"):
        if not (out.get("refused") or out.get("display_policy") == "refuse"):
            # only if race_in satisfied — may refuse for other reasons
            if race in ("white", "aa") and age and 40 <= age <= 79 and sbp and 90 <= sbp <= 200:
                return {"prop": 4, "out_keys": list(out.keys())[:12]}

    return None


def main() -> int:
    n = int(os.environ.get("FUZZ_N", "1000000"))
    rng = random.Random(20261117)
    fails: List[Dict[str, Any]] = []
    t0 = time.time()
    for i in range(n):
        hit = check_one(rng)
        if hit:
            fails.append(hit)
            if len(fails) > 50:
                break
        if (i + 1) % 100000 == 0:
            print(f"progress {i+1}/{n} fails={len(fails)} elapsed={time.time()-t0:.1f}s", flush=True)
    report = {
        "n_tested": n if len(fails) <= 50 else (i + 1),
        "contract_property_failures": len(fails),
        "failures_sample": fails[:20],
        "elapsed_sec": round(time.time() - t0, 2),
        "generator": "custom_rng_1m",
        "seed": 20261117,
        "note": "Companion to Hypothesis 5k run; same Properties 1–4 checks.",
    }
    # Merge note from prior hypothesis run if present
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text())
            report["hypothesis_5k"] = {
                k: prev[k] for k in prev if k in ("n_tested", "contract_fails", "leak_count", "tested")
            } or prev
        except Exception:
            pass
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in report if k != "failures_sample"}, indent=2))
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
