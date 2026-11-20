from mutmut_target.gates import (
    band_for,
    check_age_bounds,
    check_race_in,
    refuse_white_fallback,
    apply_consumer_band,
    public_view,
    enforce,
    CVD_BANDS,
)


def test_band_boundaries_exhaustive():
    assert band_for(0.0)["label"] == "<5%"
    assert band_for(4.9)["label"] == "<5%"
    assert band_for(5.0)["label"] == "5–<7.5%"
    assert band_for(7.49)["label"] == "5–<7.5%"
    assert band_for(7.5)["label"] == "7.5–20%"
    assert band_for(19.9)["label"] == "7.5–20%"
    assert band_for(20.0)["label"] == "≥20%"
    assert band_for(99.0)["label"] == "≥20%"
    assert band_for(100.0)["label"] == "≥20%"  # needs hi>=100 branch, not hi>100
    assert band_for(-1.0)["label"] == "Unknown"
    assert band_for(-1.0)["category"] == "Unknown"
    assert set(band_for(-1.0).keys()) == {"label", "category"}
    assert band_for(3.0)["category"] == "Low"
    assert band_for(6.0)["category"] == "Borderline"
    assert band_for(10.0)["category"] == "Intermediate"
    assert band_for(25.0)["category"] == "High"
    # table shape
    assert len(CVD_BANDS) == 4
    assert CVD_BANDS[0][0] == 0.0 and CVD_BANDS[0][1] == 5.0
    assert CVD_BANDS[1][0] == 5.0 and CVD_BANDS[1][1] == 7.5
    assert CVD_BANDS[2][0] == 7.5 and CVD_BANDS[2][1] == 20.0
    assert CVD_BANDS[3][0] == 20.0 and CVD_BANDS[3][1] == 100.0
    assert CVD_BANDS[3][2] == "≥20%" and CVD_BANDS[3][3] == "High"


def test_age_bounds_edges():
    assert check_age_bounds(None, 40, 79) == "Claim requires age; missing"
    assert check_age_bounds(39.9, 40, 79) is not None
    assert check_age_bounds(40, 40, 79) is None
    assert check_age_bounds(79, 40, 79) is None
    assert check_age_bounds(79.1, 40, 79) is not None
    assert check_age_bounds(55, None, None) is None
    assert check_age_bounds(10, 40, 79) == "Claim requires age ≥ 40"
    assert check_age_bounds(90, 40, 79) == "Claim requires age ≤ 79"


def test_race_in_edges():
    assert check_race_in(None, ["white", "aa"]) == "Claim requires race; missing"
    assert check_race_in("", ["white", "aa"]) == "Claim requires race; missing"
    assert check_race_in("asian", ["white", "aa"]) == "Claim requires race in ['white', 'aa']; got asian"
    assert check_race_in("White", ["white", "aa"]) is None
    assert check_race_in("AA", ["white", "aa"]) is None


def test_white_fallback_refuses_pce_only():
    out = refuse_white_fallback("pce_ascvd", {"risk_pct": 10, "legacy_white_fallback": True})
    assert out["refused"] is True
    assert out["gate"] == "prohibited_use"
    assert out["display_policy"] == "refuse"
    assert out["risk_pct"] is None
    assert out["note"] == "White-equation fallback is prohibited for PCE"
    # no flag → unchanged
    ok = refuse_white_fallback("pce_ascvd", {"risk_pct": 10})
    assert not ok.get("refused")
    assert ok["risk_pct"] == 10
    # wrong claim
    ok2 = refuse_white_fallback("prevent_ascvd", {"risk_pct": 10, "legacy_white_fallback": True})
    assert not ok2.get("refused")
    assert ok2["risk_pct"] == 10


def test_consumer_band_and_clinician():
    # default audience must be consumer
    out = apply_consumer_band({"risk_pct": 12.0})
    assert out["shown_as"] == "band"
    assert out["display_policy"] == "band"
    assert out["risk_pct"] is None
    assert out["risk_pct_exact"] == 12.0
    assert out["risk_band_label"] == "7.5–20%"
    # already refused stays refused / clears pct via refused key
    r = apply_consumer_band({"risk_pct": 12.0, "refused": True, "display_policy": "number"})
    assert r["risk_pct"] is None
    r2 = apply_consumer_band({"risk_pct": 12.0, "display_policy": "refuse"})
    assert r2["risk_pct"] is None
    # clinician keeps number
    clin = apply_consumer_band({"risk_pct": 12.0}, audience="clinician")
    assert clin["risk_pct"] == 12.0
    assert clin.get("shown_as") != "band"
    # missing risk
    m = apply_consumer_band({"risk_pct": None})
    assert m.get("shown_as") != "band"


def test_public_view_strips_all_exact_keys():
    pub = public_view({
        "a": 1,
        "risk_pct_exact": 9,
        "relative_risk_exact": 1.2,
        "_audit_exact": True,
        "nested": {"risk_pct_exact": 2, "ok": 3},
        "xs": [{"relative_risk_exact": 4, "y": 5}],
    })
    assert pub["a"] == 1
    assert "risk_pct_exact" not in pub
    assert "relative_risk_exact" not in pub
    assert "_audit_exact" not in pub
    assert "risk_pct_exact" not in pub["nested"]
    assert pub["nested"]["ok"] == 3
    assert "relative_risk_exact" not in pub["xs"][0]
    assert pub["xs"][0]["y"] == 5
    assert public_view(3) == 3
    assert public_view([{"risk_pct_exact": 1}]) == [{}]


def test_enforce_pipeline_full():
    r = enforce({"risk_pct": 8, "age": 22, "race": "white"}, claim_id="pce_ascvd")
    assert r["refused"] is True and r["display_policy"] == "refuse" and r["risk_pct"] is None
    r2 = enforce({"risk_pct": 8, "age": 55, "race": "asian"}, claim_id="pce_ascvd", race_allowed=["white", "aa"])
    assert r2["refused"] is True and r2["gate"] == "claim_requires" and r2["display_policy"] == "refuse"
    r3 = enforce({"risk_pct": 8, "age": 55, "race": "white", "legacy_white_fallback": True}, claim_id="pce_ascvd")
    assert r3["refused"] is True and r3["gate"] == "prohibited_use"
    r4 = enforce({"risk_pct": 8, "age": 55, "race": "white"}, claim_id="pce_ascvd", race_allowed=["white", "aa"])
    assert not r4.get("refused")
    assert r4.get("shown_as") == "band"
    assert r4.get("risk_pct") is None
    assert r4.get("risk_pct_exact") == 8
    assert "risk_pct_exact" not in public_view(r4)
    # clinician path keeps exact when no refuse
    r5 = enforce({"risk_pct": 8, "age": 55, "race": "white"}, claim_id="pce_ascvd", audience="clinician", race_allowed=["white", "aa"])
    assert r5.get("risk_pct") == 8
    # default age bounds must accept 40 and 79
    r6 = enforce({"risk_pct": 8, "age": 40, "race": "white"}, claim_id="pce_ascvd", race_allowed=["white", "aa"])
    assert not r6.get("refused")
    r7 = enforce({"risk_pct": 8, "age": 79, "race": "white"}, claim_id="pce_ascvd", race_allowed=["white", "aa"])
    assert not r7.get("refused")
    # default audience consumer
    r8 = enforce({"risk_pct": 8, "age": 55, "race": "white"}, claim_id="pce_ascvd", race_allowed=["white", "aa"])
    assert r8.get("shown_as") == "band"
