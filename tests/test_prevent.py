from prevent_equations import prevent_10yr


def test_prevent_runs_without_race():
    r = prevent_10yr(
        sex="female",
        age=50,
        total_chol=200,
        hdl_chol=55,
        sbp=120,
        diabetes=False,
        current_smoker=False,
        bmi=26,
        egfr=90,
        bp_treated=False,
    )
    assert r is not None
    assert r["race_free"] is True
    assert 0 < r["risk_pct"] < 40


def test_prevent_male_smoker_higher():
    base = dict(
        sex="male", age=55, total_chol=220, hdl_chol=45, sbp=138,
        diabetes=False, bmi=28, egfr=85, bp_treated=True,
    )
    ns = prevent_10yr(current_smoker=False, **base)
    sm = prevent_10yr(current_smoker=True, **base)
    assert sm["risk_pct"] >= ns["risk_pct"]
