"""PCE golden vectors — Goff / ACC reference profiles."""
from risk_calculators import pooled_cohort_cvd_10yr, PCE_VALID_RACES


def test_pce_refuses_unsupported_race():
    r = pooled_cohort_cvd_10yr(
        55, "female", 213, 50, 120, False, False, False, race="south_asian"
    )
    assert r is None
    assert "south_asian" not in PCE_VALID_RACES


def test_white_female_not_100_percent():
    """Regression: prior bug returned 100% for this profile."""
    r = pooled_cohort_cvd_10yr(
        55, "female", 213, 50, 120, False, False, False, race="white"
    )
    assert r is not None
    assert r["risk_pct"] < 20
    assert r["risk_pct"] > 0.5
    # Published ACC worked example ≈2.1%; tight transcription regression bound
    assert abs(r["risk_pct"] - 2.1) < 0.35


def test_aa_female_ballpark():
    r = pooled_cohort_cvd_10yr(
        55, "female", 213, 50, 120, False, False, False, race="aa"
    )
    assert r is not None
    assert 0.5 < r["risk_pct"] < 15


def test_white_male_ballpark():
    r = pooled_cohort_cvd_10yr(
        55, "male", 213, 50, 120, False, False, False, race="white"
    )
    assert r is not None
    assert 2 < r["risk_pct"] < 15


def test_other_race_no_silent_white():
    assert pooled_cohort_cvd_10yr(
        55, "female", 213, 50, 120, False, False, False, race="other"
    ) is None
