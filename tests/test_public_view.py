"""Serving-path must never leak exact percents."""
from disclosure import apply_disclosure, public_view
from risk_engine import compute_risk_scores


DAILY = [{
    "sleep": 7, "steps": 8000, "stress_level": 4, "active_minutes": 30,
    "veg_servings": 3, "fruit_servings": 2, "red_meat_servings": 1, "processed_meat": 0,
}] * 14
LABS = {"total_cholesterol": 210, "hdl_cholesterol": 55, "egfr": 90}


def _user(**kw):
    u = {
        "age": 55, "sex": "female", "sex_for_equation": "female",
        "height": 165, "weight": 70, "waist_cm": 80, "systolic": 128,
        "race": "white", "smoking_status": "never", "bp_medication": 0,
        "existing_diabetes": 0, "high_glucose_history": 0,
        "family_history_diabetes": 0, "family_history_cancer": 0,
        "alcohol_per_week": 0, "region": "global",
    }
    u.update(kw)
    return u


def _assert_no_exact(obj):
    if isinstance(obj, dict):
        assert "risk_pct_exact" not in obj
        for v in obj.values():
            _assert_no_exact(v)
    elif isinstance(obj, list):
        for v in obj:
            _assert_no_exact(v)


def test_public_view_strips_exact_from_honest_cvd():
    risk = compute_risk_scores(_user(), DAILY, LABS, mode="honest")
    assert risk["CVD"].get("risk_pct_exact") is not None  # internal audit field
    pub = public_view(risk)
    _assert_no_exact(pub)
    assert pub["CVD"].get("risk_band_label")
    assert pub["CVD"].get("risk_pct") is None


def test_public_view_strips_comparison_pce_percent():
    risk = compute_risk_scores(_user(prefer_pce=False), DAILY, LABS, mode="honest")
    cvd = risk["CVD"]
    if cvd.get("comparison_pce"):
        # Inject a leaky field as if a future regression added it
        cvd["comparison_pce"]["risk_pct"] = 9.99
        cvd["comparison_pce"]["risk_pct_exact"] = 9.99
    pub = public_view(risk)
    cp = (pub.get("CVD") or {}).get("comparison_pce") or {}
    assert "risk_pct" not in cp
    assert "risk_pct_exact" not in cp


def test_findrisc_interval_policy_when_waist_missing():
    risk = compute_risk_scores(_user(waist_cm=None), DAILY, LABS, mode="honest")
    diab = risk["Diabetes"]
    assert diab.get("score_range")
    assert diab.get("shown_as") == "interval" or diab.get("display_policy") == "interval"
    assert diab.get("risk_pct") is None


def test_pce_claim_requires_reject_unsupported_race_payload():
    raw = {"risk_pct": 5.0, "race": "south_asian", "age": 55}
    out = apply_disclosure(raw, mode="honest", claim_id="pce_ascvd")
    assert out.get("refused")
    assert out.get("gate") in ("claim_requires", "prohibited_use")
