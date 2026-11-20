import os
os.environ.setdefault("STUDY_ALLOW_BASELINE", "1")
from disclosure import apply_disclosure, public_view, DisclosureError, CVD_BANDS, _band_for


def test_unknown_claim_fails():
    try:
        apply_disclosure({"risk_pct": 1}, mode="honest", claim_id="not_real")
        assert False
    except DisclosureError:
        pass


def test_consumer_bands_or_clears():
    out = apply_disclosure(
        {"risk_pct": 12.0, "sbp": 130, "age": 50, "audience": "consumer"},
        mode="honest", claim_id="prevent_ascvd",
    )
    pub = public_view(out)
    assert "risk_pct_exact" not in pub
    assert pub.get("risk_pct_exact") is None
    if out.get("shown_as") == "band":
        assert out.get("risk_pct") is None
        assert out.get("risk_band_label")


def test_white_fallback_refuses():
    out = apply_disclosure(
        {"risk_pct": 10, "sbp": 130, "age": 55, "race": "white",
         "legacy_white_fallback": True, "audience": "consumer"},
        mode="honest", claim_id="pce_ascvd",
    )
    assert out.get("refused") is True
    assert out.get("display_policy") == "refuse"
    assert out.get("risk_pct") is None


def test_clinician_not_overrefused():
    out = apply_disclosure(
        {"risk_pct": 8.2, "sbp": 128, "age": 55, "race": "white", "audience": "clinician"},
        mode="honest", claim_id="pce_ascvd",
    )
    assert not (out.get("refused") or out.get("display_policy") == "refuse")


def test_public_view_strips_relative_and_exact():
    pub = public_view({
        "relative_risk_exact": 1.4,
        "risk_pct_exact": 8.2,
        "_audit_exact": True,
        "risk_pct": 5.0,
        "nested": {"risk_pct_exact": 9.1},
    })
    assert "relative_risk_exact" not in pub
    assert "risk_pct_exact" not in pub
    assert "_audit_exact" not in pub
    assert "risk_pct_exact" not in (pub.get("nested") or {})


def test_age_out_of_range_refuses():
    out = apply_disclosure(
        {"risk_pct": 8.0, "sbp": 128, "age": 22, "audience": "consumer"},
        mode="honest", claim_id="prevent_ascvd",
    )
    assert out.get("refused") is True
    assert out.get("display_policy") == "refuse"
    assert out.get("risk_pct") is None


def test_age_over_79_refuses_pce():
    out = apply_disclosure(
        {"risk_pct": 8.0, "sbp": 128, "age": 82, "race": "white", "audience": "consumer"},
        mode="honest", claim_id="pce_ascvd",
    )
    assert out.get("refused") is True or out.get("risk_pct") is None


def test_missing_sbp_refuses():
    out = apply_disclosure(
        {"risk_pct": 8.0, "age": 55, "audience": "consumer"},
        mode="honest", claim_id="prevent_ascvd",
    )
    assert out.get("refused") is True or out.get("risk_pct") is None


def test_baseline_requires_env():
    prev = os.environ.pop("STUDY_ALLOW_BASELINE", None)
    try:
        try:
            apply_disclosure({"risk_pct": 5.0, "age": 55, "sbp": 128}, mode="baseline", claim_id="legacy_baseline")
            assert False
        except DisclosureError:
            pass
    finally:
        if prev is not None:
            os.environ["STUDY_ALLOW_BASELINE"] = prev
        else:
            os.environ["STUDY_ALLOW_BASELINE"] = "1"


def test_band_for_thresholds():
    b = _band_for(3.0, CVD_BANDS)
    assert b["label"]
    b2 = _band_for(12.0, CVD_BANDS)
    assert b2["label"]


def test_public_view_list_and_scalar():
    assert public_view([{"risk_pct_exact": 1.0}]) == [{}]
    assert public_view(3) == 3


def test_consumer_low_risk_bands():
    out = apply_disclosure(
        {"risk_pct": 2.0, "sbp": 120, "age": 45, "audience": "consumer"},
        mode="honest", claim_id="prevent_ascvd",
    )
    assert out.get("shown_as") in ("band", "refuse", "number", "interval", None) or out.get("refused")
    pub = public_view(out)
    assert "risk_pct_exact" not in pub
