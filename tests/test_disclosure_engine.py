"""Honest disclosure: no silent waist, PREVENT for all races, suppress fiction."""
from risk_engine import compute_risk_scores


def _user(**kw):
    base = {
        "age": 45,
        "sex": "female",
        "sex_for_equation": "female",
        "height": 165,
        "weight": 70,
        "systolic": 128,
        "race": "south_asian",
        "smoking_status": "never",
        "bp_medication": 0,
        "existing_diabetes": 0,
        "high_glucose_history": 0,
        "family_history_diabetes": 0,
        "family_history_cancer": 0,
        "alcohol_per_week": 0,
        "region": "global",
    }
    base.update(kw)
    return base


def _daily(n=14):
    return [
        {
            "date": f"2026-01-{i+1:02d}",
            "sleep": 7.5,
            "steps": 8000,
            "stress_level": 4,
            "active_minutes": 30,
            "veg_servings": 3,
            "fruit_servings": 2,
            "red_meat_servings": 1,
            "processed_meat": 0,
        }
        for i in range(n)
    ]


def _labs():
    return {"total_cholesterol": 210, "hdl_cholesterol": 55, "egfr": 95}


def test_south_asian_gets_prevent_not_white_pce():
    risk = compute_risk_scores(_user(), _daily(), _labs(), mode="honest")
    cvd = risk["CVD"]
    assert not cvd.get("refused")
    assert cvd.get("equation") == "PREVENT" or cvd.get("claim_id") == "prevent_ascvd"
    assert cvd.get("race_free") is True or cvd.get("claim_id") == "prevent_ascvd"


def test_missing_waist_does_not_equal_cutoff():
    u = _user(waist_cm=None)
    risk = compute_risk_scores(u, _daily(), _labs(), mode="honest")
    diab = risk["Diabetes"]
    # Must be interval or note — not a silent single FINDRISC with +3 waist
    assert diab.get("score_range") or "waist" in (diab.get("note") or "").lower()
    assert diab.get("score") is None or "unmeasured" in (diab.get("risk_category") or "").lower()


def test_missing_sbp_refuses_cvd():
    u = _user(systolic=None)
    risk = compute_risk_scores(u, _daily(), _labs(), mode="honest")
    assert risk["CVD"].get("refused") or risk["CVD"].get("gate") == "missing_sbp"


def test_under_30_not_green_low_risk():
    u = _user(age=28)
    risk = compute_risk_scores(u, _daily(), _labs(), mode="honest")
    cvd = risk["CVD"]
    assert cvd.get("refused") or cvd.get("gate") == "age_range"
    assert cvd.get("color") != "green" or cvd.get("risk_pct") is None


def test_honest_mode_no_health_age_hero():
    risk = compute_risk_scores(_user(), _daily(), _labs(), mode="honest")
    assert risk.get("_health_age") in (None, {})
    assert risk.get("_trajectory")


def test_honest_cancer_no_rr_product():
    risk = compute_risk_scores(_user(), _daily(), _labs(), mode="honest")
    assert risk["Cancer"].get("relative_risk") is None


def test_baseline_still_has_health_age():
    risk = compute_risk_scores(_user(), _daily(), _labs(), mode="baseline")
    assert risk.get("_health_age") and risk["_health_age"].get("health_age")


def test_sex_other_without_equation_sex_refuses():
    u = _user(sex="other", sex_for_equation="")
    risk = compute_risk_scores(u, _daily(), _labs(), mode="honest")
    assert risk["CVD"].get("gate") == "sex_equation"
