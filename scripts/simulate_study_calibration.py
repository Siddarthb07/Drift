#!/usr/bin/env python3
"""
Monte Carlo calibration of analyze_study under known truth.

  null     — identical arms → empirical Type I rate must ≈ α (not ≫ α).
  alt_d025 — honest lower overconfidence by Cohen's d≈0.25 → power ≈ 0.8 at N=252/arm.

Also writes one concrete null JSONL fixture and analyzes it to show
fail_to_reject (no issue flagged) when there is no effect.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analyze_study import (  # noqa: E402
    ALPHA,
    VIGNETTE_IDS,
    analyze_observations,
    warranted,
)

KEYS = json.loads((ROOT / "study" / "warranted_certainty.json").read_text())["keys"]


def _clip_likert(x: float) -> int:
    return int(max(1, min(7, round(x))))


def simulate_participant(
    rng: random.Random,
    *,
    arm: str,
    pid: str,
    effect_shift: float = 0.0,
    noise_sd: float = 1.0,
) -> List[dict]:
    """
    effect_shift: subtracted from honest-arm stated certainty (negative = less overconfident).
    Under null, effect_shift=0 for both arms.
    """
    rows = []
    for vid in VIGNETTE_IDS:
        w = float(KEYS[vid])
        # baseline mean anchored near warranted; honest shifted by effect_shift
        mean = w + (effect_shift if arm == "honest" else 0.0)
        stated = _clip_likert(rng.gauss(mean, noise_sd))
        care = _clip_likert(rng.gauss(5.5 if vid.startswith("v6") else 4.0, 0.8))
        rows.append(
            {
                "prolific_id": pid,
                "arm": arm,
                "vignette": vid,
                "overconfidence": stated,
                "care_seeking": care if vid.startswith("v6") else None,
                "mc_race_correct": rng.random() < (0.75 if arm == "honest" else 0.55),
                "mc_health_age_correct": rng.random() < (0.70 if arm == "honest" else 0.50),
                "attention_ok": True,
            }
        )
    return rows


def simulate_dataset(
    rng: random.Random,
    *,
    n_per_arm: int,
    effect_shift: float,
) -> List[dict]:
    obs: List[dict] = []
    for i in range(n_per_arm):
        obs.extend(
            simulate_participant(rng, arm="honest", pid=f"H{i}", effect_shift=effect_shift)
        )
        obs.extend(
            simulate_participant(rng, arm="baseline", pid=f"B{i}", effect_shift=0.0)
        )
    return obs


def run_reps(
    *,
    scenario: str,
    n_reps: int,
    n_per_arm: int,
    effect_shift: float,
    seed: int,
) -> Dict:
    rejects = 0
    ni_holds = 0
    pvals = []
    for r in range(n_reps):
        rng = random.Random(seed + r * 10007)
        obs = simulate_dataset(rng, n_per_arm=n_per_arm, effect_shift=effect_shift)
        out = analyze_observations(obs)
        primary = out["primary_calibrated_overconfidence"]
        pvals.append(primary["p_two_sided"])
        if primary["reject_null"]:
            rejects += 1
        if out["secondary_care_seeking_v6"]["tost"]["noninferiority_holds"]:
            ni_holds += 1
    rate = rejects / n_reps
    return {
        "scenario": scenario,
        "n_reps": n_reps,
        "n_per_arm": n_per_arm,
        "effect_shift": effect_shift,
        "alpha": ALPHA,
        "empirical_reject_rate": round(rate, 4),
        "empirical_care_ni_hold_rate": round(ni_holds / n_reps, 4),
        "mean_p": round(sum(pvals) / len(pvals), 4),
        "passes_type_I_calibration": (
            scenario.startswith("null") and (0.02 <= rate <= 0.08)
        )
        if scenario.startswith("null")
        else None,
        "passes_power_target": (
            (not scenario.startswith("null")) and rate >= 0.70
        )
        if not scenario.startswith("null")
        else None,
    }


def write_null_fixture(path: Path, *, n_per_arm: int = 300, seed: int = 42) -> Dict:
    rng = random.Random(seed)
    obs = simulate_dataset(rng, n_per_arm=n_per_arm, effect_shift=0.0)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in obs:
            fh.write(json.dumps(row) + "\n")
    result = analyze_observations(obs)
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=400)
    ap.add_argument("--seed", type=int, default=20261025)
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / "docs" / "facct" / "study_calibration.json",
    )
    ap.add_argument(
        "--fixture",
        type=Path,
        default=ROOT / "study" / "simulated" / "null_arm_equal.jsonl",
    )
    args = ap.parse_args()

    # Null at confirmatory N
    null = run_reps(
        scenario="null_n300",
        n_reps=args.reps,
        n_per_arm=300,
        effect_shift=0.0,
        seed=args.seed,
    )
    # Alternative: shift honest stated certainty down by ~0.4 Likert ≈ d~0.25–0.35
    # with noise_sd=1.0 on 4-vignette means (participant SE smaller)
    alt = run_reps(
        scenario="alt_shift_neg0.35_n252",
        n_reps=args.reps,
        n_per_arm=252,
        effect_shift=-0.35,
        seed=args.seed + 1,
    )
    # Small-N null (pilot) — expect Type I still near α, not inflated
    null_pilot = run_reps(
        scenario="null_n40_pilot",
        n_reps=args.reps,
        n_per_arm=20,
        effect_shift=0.0,
        seed=args.seed + 2,
    )

    fixture_result = write_null_fixture(args.fixture, n_per_arm=300, seed=args.seed)
    primary = fixture_result["primary_calibrated_overconfidence"]

    report = {
        "method": "Monte Carlo; identical DGP under null; Welch two-sided α=0.05",
        "seed": args.seed,
        "reps": args.reps,
        "calibration": [null, null_pilot, alt],
        "null_fixture": {
            "path": str(args.fixture.relative_to(ROOT)),
            "n_participants": fixture_result["n_participants"],
            "p_two_sided": primary["p_two_sided"],
            "reject_null": primary["reject_null"],
            "decision": primary["decision"],
            "plain_language": primary["plain_language"],
            "expect": "fail_to_reject_null_no_issue_flagged when arms truly equal",
        },
        "gates": {
            "null_type_I_in_02_08": bool(null["passes_type_I_calibration"]),
            "pilot_type_I_in_02_08": bool(null_pilot["passes_type_I_calibration"]),
            "alt_power_ge_70": bool(alt["passes_power_target"]),
            "null_fixture_no_issue": primary["decision"] == "fail_to_reject_null_no_issue_flagged",
        },
        "healthcare_note": (
            "Under no true arm difference the analyzer must usually NOT reject. "
            "A single p≈0.05 is not an 'issue'; reject only at the prereg α threshold."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    failed = not all(report["gates"].values())
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
