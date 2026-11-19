#!/usr/bin/env python3
"""Run 6: p50/p99 latency overhead of disclosure contract over raw payload."""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("STUDY_ALLOW_BASELINE", "1")

from disclosure import apply_disclosure, public_view, load_claims  # noqa: E402

OUT = ROOT / "docs" / "jbhi" / "outside_corpus" / "latency_report.json"


def pct(xs, p):
    s = sorted(xs)
    i = min(len(s) - 1, max(0, int(round((p / 100) * (len(s) - 1)))))
    return s[i]


def main() -> int:
    load_claims(refresh=True)
    n = 100_000
    raw = {"risk_pct": 11.7, "sbp": 128, "age": 55, "race": "white", "audience": "consumer"}
    # warmup
    for _ in range(1000):
        public_view(apply_disclosure(dict(raw), mode="honest", claim_id="prevent_ascvd"))

    base = []
    for _ in range(n):
        t0 = time.perf_counter()
        _ = dict(raw)
        base.append((time.perf_counter() - t0) * 1000)

    contract = []
    for _ in range(n):
        t0 = time.perf_counter()
        public_view(apply_disclosure(dict(raw), mode="honest", claim_id="prevent_ascvd"))
        contract.append((time.perf_counter() - t0) * 1000)

    overhead = [c - b for c, b in zip(contract, base)]
    report = {
        "n": n,
        "baseline_dict_copy_ms": {"p50": pct(base, 50), "p99": pct(base, 99), "mean": statistics.fmean(base)},
        "contract_plus_public_view_ms": {"p50": pct(contract, 50), "p99": pct(contract, 99), "mean": statistics.fmean(contract)},
        "overhead_ms": {"p50": pct(overhead, 50), "p99": pct(overhead, 99), "mean": statistics.fmean(overhead)},
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
