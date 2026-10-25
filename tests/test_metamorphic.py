"""Black-box metamorphic honesty checks (not flag-based)."""
from risk_engine import compute_risk_scores


DAILY = [{
    "sleep": 7, "steps": 8000, "stress_level": 4, "active_minutes": 30,
    "veg_servings": 3, "fruit_servings": 2, "red_meat_servings": 1, "processed_meat": 0,
}] * 14
LABS = {"total_cholesterol": 210, "hdl_cholesterol": 55, "egfr": 90}


def _user(**kw):
    u = {
        "age": 50, "sex": "female", "sex_for_equation": "female",
        "height": 165, "weight": 70, "waist_cm": 80, "systolic": 128,
        "race": "white", "smoking_status": "never", "bp_medication": 0,
        "existing_diabetes": 0, "high_glucose_history": 0,
        "family_history_diabetes": 0, "family_history_cancer": 0,
        "alcohol_per_week": 0, "region": "global",
    }
    u.update(kw)
    return u


def _shown(cvd):
    return (
        not cvd.get("refused")
        and (cvd.get("risk_band_label") or cvd.get("risk_pct_exact") is not None or cvd.get("risk_pct") is not None)
    )


def test_honest_race_swap_identical_prevent():
    a = compute_risk_scores(_user(race="white"), DAILY, LABS, mode="honest")["CVD"]
    b = compute_risk_scores(_user(race="south_asian"), DAILY, LABS, mode="honest")["CVD"]
    assert _shown(a) and _shown(b)
    assert a.get("risk_pct_exact") == b.get("risk_pct_exact")
    assert a.get("risk_band_label") == b.get("risk_band_label")


def test_missing_sbp_no_numeric():
    cvd = compute_risk_scores(_user(systolic=None), DAILY, LABS, mode="honest")["CVD"]
    assert cvd.get("refused") or cvd.get("gate") == "missing_sbp"
    assert cvd.get("risk_pct") is None
    assert cvd.get("risk_pct_exact") is None


def test_bmi_40_still_gets_ascvd_estimate():
    # ASCVD BMI coeffs are 0 — must not refuse solely for BMI≥40
    u = _user(height=165, weight=110)  # BMI ~40.4
    cvd = compute_risk_scores(u, DAILY, LABS, mode="honest")["CVD"]
    assert _shown(cvd)
    assert cvd.get("gate") != "bmi_range"


def test_legacy_south_asian_fallback_flag_when_scored():
    risk = compute_risk_scores(_user(race="south_asian", age=52), DAILY, LABS, mode="baseline")
    cvd = risk["CVD"]
    assert cvd.get("legacy_white_fallback") is True
    assert cvd.get("risk_pct") is not None


def test_unknown_claim_fails_closed():
    from disclosure import DisclosureError, apply_disclosure
    try:
        apply_disclosure({"risk_pct": 1.0}, mode="honest", claim_id="not_a_real_claim")
        assert False, "expected DisclosureError"
    except DisclosureError:
        pass


def test_honest_never_emits_health_age():
    risk = compute_risk_scores(_user(), DAILY, LABS, mode="honest")
    assert not (risk.get("_health_age") or {}).get("health_age")
