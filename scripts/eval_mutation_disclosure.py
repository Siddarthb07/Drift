#!/usr/bin/env python3
"""Mutation score for disclosure.py / public_view (expanded mutant set).

Reports: mutant count, killed, survived, equivalent, file scope.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "jbhi" / "outside_corpus" / "mutation_report.json"
SRC_PATH = ROOT / "disclosure.py"


def make_mutants(src: str) -> List[Tuple[str, str]]:
    """(id, mutant_source) — semantic mutants in disclosure.py scope only."""
    mutants: List[Tuple[str, str]] = []

    def add(mid: str, a: str, b: str) -> None:
        if a not in src:
            return
        m = src.replace(a, b, 1)
        if m != src:
            mutants.append((mid, m))

    add("strip_empty",
        '_PUBLIC_STRIP_KEYS = (\n    "risk_pct_exact",\n    "relative_risk_exact",\n    "_audit_exact",\n)',
        '_PUBLIC_STRIP_KEYS = ()')
    add("strip_drop_exact",
        '"risk_pct_exact",\n',
        '')
    add("unknown_softfail",
        'raise DisclosureError(f"Unknown claim_id: {claim_id}")',
        'return dict(raw)  # MUTANT: soft-fail unknown claim')
    add("band_keep_pct",
        'out["risk_pct"] = None\n        out["shown_as"] = "band"',
        'out["shown_as"] = "band"  # MUTANT: keep risk_pct')
    add("white_fb_disable",
        'if claim_id == "pce_ascvd" and out.get("legacy_white_fallback"):',
        'if False and claim_id == "pce_ascvd" and out.get("legacy_white_fallback"):')
    add("audience_always_consumer",
        'audience = str(out.get("audience") or "consumer").lower()',
        'audience = "consumer"  # MUTANT: ignore clinician')
    # Flip a comparison
    add("age_gate_invert",
        "if age is not None and (age < lo or age > hi):",
        "if age is not None and (age >= lo and age <= hi):  # MUTANT invert")
    add("public_view_identity",
        "def public_view(payload:",
        "def public_view_MUTANT_DISABLED(payload:")  # may not apply — skip if signature differs
    # Broader: remove a strip key via regex
    m2 = re.sub(r'"relative_risk_exact",\s*', '', src, count=1)
    if m2 != src:
        mutants.append(("strip_drop_relative", m2))
    # Soften refuse to band
    add("refuse_to_pass",
        'out["display_policy"] = "refuse"\n        return out\n\n    # Predicate checks',
        'out["display_policy"] = "pass"  # MUTANT\n        return out\n\n    # Predicate checks')
    add("band_policy_skip",
        'if policy in ("band", "interval") and out.get("risk_pct") is not None:',
        'if False and policy in ("band", "interval") and out.get("risk_pct") is not None:  # MUTANT')
    add("white_fb_no_refuse_flag",
        'if claim_id == "pce_ascvd" and out.get("legacy_white_fallback"):\n        out["refused"] = True',
        'if claim_id == "pce_ascvd" and out.get("legacy_white_fallback"):\n        out["refused"] = False  # MUTANT')
    add("fail_open_unknown",
        'raise DisclosureError(f"Unknown claim_id: {claim_id}")',
        'pass  # MUTANT fail-open')
    add("consumer_exact_keep",
        'if audience in ("consumer", "patient", "public"):',
        'if False and audience in ("consumer", "patient", "public"):  # MUTANT')
    add("public_view_noop",
        'if k in _PUBLIC_STRIP_KEYS:\n                continue',
        'if False and k in _PUBLIC_STRIP_KEYS:\n                continue  # MUTANT')
    add("age_gate_disabled",
        "pred_fail = _check_requires(claim, out)",
        "pred_fail = None  # MUTANT skip requires")
    # Broader strip-all-disabled mutant
    m4 = src.replace("_PUBLIC_STRIP_KEYS", "_PUBLIC_STRIP_KEYS_DISABLED", 1)
    if m4 != src and "_PUBLIC_STRIP_KEYS_DISABLED =" not in m4:
        mutants.append(("strip_keys_rename", m4))
    return mutants


PROBE = r'''
import os, sys
sys.path.insert(0, os.environ["MUTANT_ROOT"])
from disclosure import apply_disclosure, public_view, DisclosureError

raw = {"risk_pct": 12.0, "sbp": 130, "age": 50, "audience": "consumer"}
out = apply_disclosure(dict(raw), mode="honest", claim_id="prevent_ascvd")
pub = public_view(out)
assert "risk_pct_exact" not in pub
assert pub.get("risk_pct") is None or out.get("shown_as") == "band" or out.get("refused")
# consumer must not see exact percent under public_view
assert pub.get("risk_pct_exact") is None
try:
    apply_disclosure({"risk_pct": 1}, mode="honest", claim_id="nope")
    raise SystemExit(2)
except DisclosureError:
    pass
out2 = apply_disclosure(
    {"risk_pct": 10, "sbp": 130, "age": 55, "race": "white",
     "legacy_white_fallback": True, "audience": "consumer"},
    mode="honest", claim_id="pce_ascvd",
)
assert out2.get("refused") is True and out2.get("display_policy") == "refuse"
# clinician exact should not be over-refused for in-range PCE
out3 = apply_disclosure(
    {"risk_pct": 8.2, "sbp": 128, "age": 55, "race": "white", "audience": "clinician"},
    mode="honest", claim_id="pce_ascvd",
)
assert not (out3.get("refused") or out3.get("display_policy") == "refuse")
# age out of range must refuse via claim requires
out4 = apply_disclosure(
    {"risk_pct": 8.0, "sbp": 128, "age": 22, "audience": "consumer"},
    mode="honest", claim_id="prevent_ascvd",
)
assert out4.get("refused") is True
assert out4.get("display_policy") == "refuse"
assert out4.get("risk_pct") is None
# band path: consumer percent cleared
if out.get("shown_as") == "band":
    assert out.get("risk_pct") is None
# relative_risk_exact must be stripped from public view
pub2 = public_view({"relative_risk_exact": 1.4, "risk_pct": 5.0, "audience": "consumer",
                    "sbp": 120, "age": 50})
assert "relative_risk_exact" not in pub2
# refuse policy must stick when set by apply_disclosure on white fallback
assert out2.get("refused") is True
assert out2.get("display_policy") == "refuse"
assert out2.get("risk_pct") is None
# consumer band must clear the point percent
out5 = apply_disclosure(
    {"risk_pct": 12.0, "sbp": 130, "age": 50, "audience": "consumer"},
    mode="honest", claim_id="prevent_ascvd",
)
if out5.get("shown_as") == "band":
    assert out5.get("risk_pct") is None
print("OK")
'''


def run_probe(td: Path, env: dict) -> Tuple[bool, str]:
    r = subprocess.run([sys.executable, "-c", PROBE], cwd=td, env=env, capture_output=True, text=True)
    return (r.returncode == 0 and "OK" in r.stdout), (r.stderr or r.stdout)[-400:]


def main() -> int:
    src = SRC_PATH.read_text()
    mutants = make_mutants(src)
    details: List[Dict[str, Any]] = []
    killed = survived = equivalent = 0

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        shutil.copy(ROOT / "claims.yaml", tdp / "claims.yaml")
        env = {**os.environ, "MUTANT_ROOT": td, "PYTHONPATH": td, "STUDY_ALLOW_BASELINE": "1"}

        (tdp / "disclosure.py").write_text(src)
        ok, err = run_probe(tdp, env)
        details.append({"mutant": "baseline", "killed": False, "passed": ok, "stderr": err})
        if not ok:
            OUT.write_text(json.dumps({"error": "baseline probes failed", "stderr": err}, indent=2))
            print(err)
            return 1

        for mid, mut in mutants:
            if mut == src:
                equivalent += 1
                details.append({"mutant": mid, "status": "equivalent", "killed": False})
                continue
            (tdp / "disclosure.py").write_text(mut)
            # clear cached module by new process each time
            ok, err = run_probe(tdp, env)
            if ok:
                # Survived: probes still pass — either equivalent or weak suite
                # Try a stronger leak probe specific to strip mutants
                survived += 1
                details.append({"mutant": mid, "status": "survived", "killed": False, "stderr": err})
            else:
                killed += 1
                details.append({"mutant": mid, "status": "killed", "killed": True, "stderr": err[:200]})

    n = len(mutants)
    score = (killed / n) if n else 0.0
    report = {
        "file_scope": ["disclosure.py"],
        "mutant_count": n,
        "killed": killed,
        "survived": survived,
        "equivalent": equivalent,
        "mutation_score": score,
        "mutation_score_excluding_equivalent": (killed / (n - equivalent)) if (n - equivalent) else None,
        "details": details,
        "note": "Custom semantic mutants (not mutmut); equivalent = source-unchanged replacements.",
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in report if k != "details"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
