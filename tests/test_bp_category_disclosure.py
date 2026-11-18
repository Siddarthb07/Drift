"""Second disclosure domain: ACC/AHA BP categories (not PREVENT/PCE)."""
import pytest

from disclosure import DisclosureError, apply_disclosure
from bp_category_disclosure import (
    CLAIM_CATEGORY,
    classify_acc2017,
    compute_bp_category,
    compute_bp_home_average_refused,
    compute_bp_modifiable_factors,
    serve_bp_disclosure,
)


def test_classify_stage1():
    c = classify_acc2017(138, 88)
    assert c["code"] == "stage1"
    assert "Stage 1" in c["category"]


def test_classify_normal():
    assert classify_acc2017(118, 76)["code"] == "normal"


def test_missing_dbp_refuses_no_imputation():
    out = compute_bp_category({"age": 50, "systolic": 128, "diastolic": None})
    assert out.get("refused")
    assert out.get("gate") == "missing_bp"
    assert out.get("bp_category") is None
    assert out.get("claim_id") == CLAIM_CATEGORY
    assert out.get("display_policy") == "refuse"


def test_serve_strips_false_precision():
    pub = serve_bp_disclosure({"age": 50, "systolic": 128.47, "diastolic": 82.13})
    bp = pub["BP"]
    assert bp.get("sbp_mmhg") == 128
    assert bp.get("dbp_mmhg") == 82
    assert "sbp_mmhg_exact" not in bp
    assert "dbp_mmhg_exact" not in bp
    assert bp.get("bp_category") == "Stage 1 hypertension"
    assert bp.get("claim_id") == CLAIM_CATEGORY


def test_home_average_claim_refuses():
    out = compute_bp_home_average_refused([{"sbp": 130.1, "dbp": 85.2}])
    assert out.get("display_policy") == "refuse"
    assert out.get("claim_id") == "bp_home_average_heuristic"


def test_factors_only_strips_rr():
    out = compute_bp_modifiable_factors()
    assert out.get("shown_as") == "factors"
    assert out.get("relative_risk") is None
    assert out.get("factors")


def test_unknown_claim_id_fail_closed():
    with pytest.raises(DisclosureError, match="Unknown claim_id"):
        apply_disclosure({"bp_category": "Normal"}, mode="honest", claim_id="bp_fake")


def test_underage_requires_predicate():
    out = compute_bp_category({"age": 16, "systolic": 118, "diastolic": 72})
    assert out.get("refused")
    assert out.get("gate") == "claim_requires"
