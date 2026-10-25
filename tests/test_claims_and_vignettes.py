import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_validate_claims_script():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_claims.py")], cwd=ROOT)
    assert r.returncode == 0


def test_eval_vignettes_honest_beats_baseline():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "eval_vignettes.py")], cwd=ROOT)
    assert r.returncode == 0
    data = json.loads((ROOT / "docs" / "facct" / "vignette_eval.json").read_text())
    assert data["honest_mean_pass_rate"] >= 0.95
    assert data["delta_honest_minus_baseline"] > 0.15


def test_home_html_is_claim_honest():
    html = (ROOT / "templates" / "home.html").read_text(encoding="utf-8")
    assert "PhenoAge" not in html
    assert "inspired by the PhenoAge" not in html
    assert "Refuse when unsure" in html or "evidence-contingent" in html.lower()
    assert "PREVENT" in html
    assert "same algorithm cardiologists use" not in html
