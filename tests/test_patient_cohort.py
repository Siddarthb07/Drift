"""100-patient mixed cohort: clean show / elevated show / warn-refuse."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from patient_cohort_sim import run_cohort  # noqa: E402


def test_100_patient_mixed_cohort_all_pass():
    report = run_cohort(seed=42, n=100)
    assert report["by_bucket"]["clean"]["n"] == 34
    assert report["by_bucket"]["show"]["n"] == 33
    assert report["by_bucket"]["warn"]["n"] == 33
    assert report["by_bucket"]["clean"]["shown"] == 34
    assert report["by_bucket"]["warn"]["refused"] == 33
    assert report["all_passed"], report["failures"]
    assert report["pass_rate"] == 1.0
