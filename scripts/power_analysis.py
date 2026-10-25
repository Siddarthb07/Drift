#!/usr/bin/env python3
"""Approximate n for two-sample t-test (equal n) on primary overconfidence contrast."""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def n_per_arm(d: float, alpha: float = 0.05, power: float = 0.8) -> int:
    # Two-sided; normal approx with z
    z_alpha = 1.959963984540054  # ~N(0,1) 0.975
    z_beta = 0.8416212335729143  # ~0.80
    # n = 2 * ((z_a + z_b) / d)^2
    n = 2 * ((z_alpha + z_beta) / d) ** 2
    return int(math.ceil(n))


def main():
    rows = []
    for d in (0.2, 0.25, 0.3, 0.35, 0.5):
        n = n_per_arm(d)
        rows.append({
            "d": d,
            "n_per_arm": n,
            "n_total": 2 * n,
            "with_15pct_attrition_total": int(math.ceil(2 * n / 0.85)),
        })
    out = {
        "method": "two-sample equal-n z approximation for t-test",
        "alpha_two_sided": 0.05,
        "power": 0.8,
        "rows": rows,
        "chosen": rows[1],  # d=0.25
        "note": "Prereg targets d=0.25 → ~252/arm; study aims 300/arm after attrition.",
    }
    path = ROOT / "docs" / "facct" / "power_analysis.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
