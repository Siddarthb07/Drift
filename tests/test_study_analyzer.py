"""Study analyzer: correct null behavior, Type I calibration, no false 'issue' under no effect."""
from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analyze_study import (  # noqa: E402
    ALPHA,
    VIGNETTE_IDS,
    analyze_observations,
    bh_fdr,
    primary_decision,
    student_t_cdf,
    welch_tost,
    welch_ttest,
)


def _rows(arm: str, pid: str, stated: float, care: float = 5.0) -> list:
    return [
        {
            "prolific_id": pid,
            "arm": arm,
            "vignette": vid,
            "overconfidence": stated,
            "care_seeking": care if vid.startswith("v6") else None,
            "mc_race_correct": True,
            "mc_health_age_correct": True,
            "attention_ok": True,
        }
        for vid in VIGNETTE_IDS
    ]


def test_t_cdf_symmetric():
    assert abs(student_t_cdf(0.0, 30) - 0.5) < 1e-6
    assert student_t_cdf(2.0, 30) > 0.97
    assert student_t_cdf(-2.0, 30) < 0.03


def test_welch_identical_samples_p_near_one():
    a = [1.0, 2.0, 3.0, 4.0, 5.0] * 20
    b = list(a)
    w = welch_ttest(a, b)
    assert w["p_two_sided"] > 0.99
    assert abs(w["mean_diff"]) < 1e-12


def test_welch_clear_difference_rejects():
    a = [0.0] * 80
    b = [1.0] * 80
    w = welch_ttest(a, b)
    assert w["p_two_sided"] < 0.001
    d = primary_decision(w["p_two_sided"])
    assert d["reject_null"] is True


def test_primary_decision_no_issue_when_p_above_alpha():
    d = primary_decision(0.20)
    assert d["reject_null"] is False
    assert d["decision"] == "fail_to_reject_null_no_issue_flagged"
    assert "no statistically significant evidence" in d["plain_language"].lower()


def test_primary_decision_boundary_alpha():
    # p == α → fail to reject (strict <)
    d = primary_decision(ALPHA)
    assert d["reject_null"] is False
    d2 = primary_decision(ALPHA - 1e-12)
    assert d2["reject_null"] is True


def test_bh_fdr_controls_family():
    # one clear hit, one null-ish
    out = bh_fdr({"a": 0.001, "b": 0.40})
    assert out["rejects"]["a"] is True
    assert out["rejects"]["b"] is False


def test_null_dataset_flags_no_issue():
    """Deterministic equal arms → analyzer must NOT flag a primary issue."""
    obs = []
    for i in range(100):
        obs.extend(_rows("honest", f"H{i}", stated=4))
        obs.extend(_rows("baseline", f"B{i}", stated=4))
    out = analyze_observations(obs)
    primary = out["primary_calibrated_overconfidence"]
    assert primary["reject_null"] is False
    assert primary["decision"] == "fail_to_reject_null_no_issue_flagged"
    assert primary["p_two_sided"] > 0.05


def test_effect_dataset_can_reject():
    obs = []
    for i in range(150):
        obs.extend(_rows("honest", f"H{i}", stated=3))  # less certain
        obs.extend(_rows("baseline", f"B{i}", stated=5))
    out = analyze_observations(obs)
    assert out["primary_calibrated_overconfidence"]["reject_null"] is True
    assert out["primary_calibrated_overconfidence"]["delta_honest_minus_baseline"] < 0


def test_care_tost_holds_when_arms_equal():
    a = [5.0, 5.5, 6.0, 5.0, 6.0] * 30
    b = list(a)
    tost = welch_tost(a, b, margin=0.5)
    assert tost["noninferiority_holds"] is True


def test_care_tost_fails_when_honest_much_worse():
    a = [2.0] * 80  # honest much lower care-seeking
    b = [6.0] * 80
    tost = welch_tost(a, b, margin=0.5)
    assert tost["noninferiority_holds"] is False


def test_monte_carlo_type_I_near_alpha():
    """Under null DGP, reject rate must sit near α — not always 'a small chance'."""
    from simulate_study_calibration import run_reps  # type: ignore

    # Modest reps for CI; band wide enough for Monte Carlo noise around α=0.05
    null = run_reps(
        scenario="null_n80",
        n_reps=80,
        n_per_arm=80,
        effect_shift=0.0,
        seed=12345,
    )
    rate = null["empirical_reject_rate"]
    assert 0.0 <= rate <= 0.15, f"Type I rate {rate} far from α=0.05"
    assert rate < 0.25  # must not reject almost always


def test_monte_carlo_power_under_effect():
    from simulate_study_calibration import run_reps  # type: ignore

    alt = run_reps(
        scenario="alt",
        n_reps=60,
        n_per_arm=200,
        effect_shift=-0.5,
        seed=99,
    )
    assert alt["empirical_reject_rate"] >= 0.65
