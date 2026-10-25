"""
PREVENT golden vectors cross-checked against published worked examples
(CVrisk / Khan 2024 base-model ASCVD 10y).

Sources:
  - CVrisk::ascvd_10y_prevent examples (vcastro.github.io/CVrisk)
  - Independent reimplementation checks citing Khan Circulation 2024 coeffs
"""
from prevent_equations import prevent_10yr


def test_golden_female_high_risk_ascvd_9_2():
    # Female 50, TC 200, HDL 45, SBP 160, eGFR 90, BMI 35,
    # BP meds yes, diabetes yes, smoker no → ASCVD 9.2%
    r = prevent_10yr(
        sex="female",
        age=50,
        total_chol=200,
        hdl_chol=45,
        sbp=160,
        diabetes=True,
        current_smoker=False,
        bmi=35,
        egfr=90,
        bp_treated=True,
        statin=False,
        outcome="ascvd",
    )
    assert r is not None
    assert abs(r["risk_pct"] - 9.2) < 0.35, r


def test_golden_male_base_ascvd_approx_2_9():
    # Male 55, TC 4.8 mmol/L ≈ 185.6 mg/dL, HDL 1.3 mmol/L ≈ 50.3,
    # SBP 130, eGFR 90, BMI 25, untreated, nondiabetic, nonsmoker → ~2.9%
    tc = 4.8 / 0.02586
    hdl = 1.3 / 0.02586
    r = prevent_10yr(
        sex="male",
        age=55,
        total_chol=tc,
        hdl_chol=hdl,
        sbp=130,
        diabetes=False,
        current_smoker=False,
        bmi=25,
        egfr=90,
        bp_treated=False,
        statin=False,
        outcome="ascvd",
    )
    assert r is not None
    assert abs(r["risk_pct"] - 2.9) < 0.4, r


def test_grid_monotonic_sbp():
    base = dict(
        sex="female", age=55, total_chol=210, hdl_chol=50, diabetes=False,
        current_smoker=False, bmi=27, egfr=90, bp_treated=False,
        statin=False, outcome="ascvd",
    )
    low = prevent_10yr(sbp=110, **base)
    high = prevent_10yr(sbp=160, **base)
    assert high["risk_pct"] > low["risk_pct"]


def test_in_range_profile_returns_estimate():
    r = prevent_10yr(
        sex="male", age=50, total_chol=200, hdl_chol=50, sbp=120,
        diabetes=False, current_smoker=False, bmi=22, egfr=90,
        bp_treated=False, statin=False,
    )
    assert r is not None
    assert r["risk_pct"] > 0
