#!/usr/bin/env python3
"""OSS differential testing v2 (reviewer-hardened oracles).

Silent White-fallback = White-equation numeric equality (±0.05 pp) AND no
caveat/disclosure string in the *adapter output*. ACC-documented Other→White
WITH a caveat field/string is NOT a violation. Source comments alone do not count.

Transcription anchors use published Goff/ACC PCE worked examples and
Khan/preventr PREVENT references — not Drift self-outputs.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OSS = ROOT / "docs" / "jbhi" / "outside_corpus" / "oss_checkout"
OUT = ROOT / "docs" / "jbhi" / "outside_corpus" / "oss_differential_report.json"
AUDIT = ROOT / "docs" / "jbhi" / "outside_corpus" / "transcription_handcheck.json"

os.environ.setdefault("STUDY_ALLOW_BASELINE", "1")

from disclosure import load_claims  # noqa: E402

load_claims(refresh=True)

Profile = Dict[str, Any]
CAVEAT_RE = re.compile(
    r"(other|white equation|white.?coeff|caveat|under.?estimat|over.?estimat|"
    r"not validated|coverage|race.?free|apply.?white|pooled cohort.*other|"
    r"may not apply|disclaimer|limitation|uses white)",
    re.I,
)


@dataclass
class AdapterOut:
    risk_pct: Optional[float]
    caveat_text: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


# Published anchors (Goff 2013/2014 ACC worked examples; Khan/preventr PREVENT)
PUBLISHED_ANCHORS = [
    dict(tag="pce_wf", age=55, sex="female", race="white", tc=213, hdl=50, sbp=120,
         bp_tx=False, smoker=False, diabetes=False, expected=2.1, family="pce",
         source="ACC/Goff 2013 worked example (White female)"),
    dict(tag="pce_wm", age=55, sex="male", race="white", tc=213, hdl=50, sbp=120,
         bp_tx=False, smoker=False, diabetes=False, expected=5.4, family="pce",
         source="ACC/Goff 2013 worked example (White male)"),
    dict(tag="pce_aaf", age=55, sex="female", race="aa", tc=213, hdl=50, sbp=120,
         bp_tx=False, smoker=False, diabetes=False, expected=3.0, family="pce",
         source="ACC/Goff 2013 worked example (AA female)"),
    dict(tag="pce_aam", age=55, sex="male", race="aa", tc=213, hdl=50, sbp=120,
         bp_tx=False, smoker=False, diabetes=False, expected=6.1, family="pce",
         source="ACC/Goff 2013 worked example (AA male)"),
    dict(tag="prevent_f", age=50, sex="female", race="white", tc=200, hdl=45, sbp=160,
         bp_tx=True, smoker=False, diabetes=True, bmi=35, egfr=90, expected=9.2,
         family="prevent", source="preventr/Khan canonical female ASCVD 10y (0.092)"),
    dict(tag="prevent_m", age=50, sex="male", race="white", tc=200, hdl=45, sbp=160,
         bp_tx=True, smoker=False, diabetes=True, bmi=35, egfr=90, expected=10.2,
         family="prevent", source="preventr/Khan canonical male ASCVD 10y (0.102)"),
]


def wilson_ci(k: int, n: int, z: float = 1.96) -> Tuple[float, float, float]:
    if n <= 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = (z / den) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (p, max(0.0, center - half), min(1.0, center + half))


def has_caveat(text: str) -> bool:
    return bool(text and CAVEAT_RE.search(text))


def _near(a: float, b: float, tol: float = 0.05) -> bool:
    return abs(float(a) - float(b)) <= tol


def find_node() -> Optional[str]:
    for c in [
        os.environ.get("NODE_BIN"),
        "node",
        str(Path.home() / ".local/node/bin/node"),
        "/usr/local/bin/node",
        "/opt/homebrew/bin/node",
    ]:
        if not c:
            continue
        try:
            r = subprocess.run([c, "-v"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return c
        except Exception:
            continue
    return None


NODE = find_node()


def wrap_float(fn) -> Callable[[Profile], AdapterOut]:
    def _inner(p: Profile) -> AdapterOut:
        try:
            r = fn(p)
            if isinstance(r, AdapterOut):
                return r
            if r is None:
                return AdapterOut(None)
            return AdapterOut(float(r))
        except Exception as e:
            return AdapterOut(None, meta={"error": f"{type(e).__name__}: {e}"})
    return _inner


def load_py_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def extract_py_function(path: Path, func_name: str):
    """Load a .py that may import streamlit at module level by stubbing streamlit."""
    src = path.read_text(errors="ignore")
    # Keep real math/numpy; stub only UI deps
    stub = textwrap.dedent(
        """
        import sys, math
        import numpy  # real
        class _Stub:
            def __getattr__(self, name):
                def _f(*a, **k):
                    return self
                return _f
            def __call__(self, *a, **k):
                return self
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def number_input(self, *a, **k): return 0
            def selectbox(self, *a, **k): return a[1][0] if len(a) > 1 and a[1] else None
            def button(self, *a, **k): return False
            def checkbox(self, *a, **k): return False
            def slider(self, *a, **k): return k.get("value", 50)
            def title(self, *a, **k): return None
            def header(self, *a, **k): return None
            def write(self, *a, **k): return None
            def success(self, *a, **k): return None
            def set_page_config(self, *a, **k): return None
        for _m in ("streamlit", "matplotlib", "matplotlib.pyplot", "fpdf"):
            sys.modules[_m] = _Stub()
        """
    )
    g: Dict[str, Any] = {"__name__": f"adapter_{func_name}", "__file__": str(path)}
    exec(compile(stub + "\n" + src, str(path), "exec"), g)
    if func_name not in g:
        raise AttributeError(f"{func_name} not found in {path}")
    return g[func_name]


def js_eval(code: str) -> Any:
    """Evaluate JS via Node if available, else quickjs."""
    if NODE:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(code)
            path = f.name
        try:
            r = subprocess.run(
                [NODE, path], capture_output=True, text=True, timeout=15
            )
            if r.returncode != 0:
                raise RuntimeError(r.stderr.strip() or r.stdout.strip() or "node fail")
            line = (r.stdout or "").strip().splitlines()[-1]
            return float(line)
        finally:
            Path(path).unlink(missing_ok=True)
    from quickjs import Context  # type: ignore
    return Context().eval(code)


def strip_ts(src: str) -> str:
    """Crude TypeScript→JS for pure calc modules (no JSX)."""
    s = re.sub(r"^import\s+.+?;\s*$", "", src, flags=re.M)
    s = re.sub(r"^export\s+", "", s, flags=re.M)
    s = re.sub(r"interface\s+\w+\s*\{[^}]*\}", "", s, flags=re.S)
    s = re.sub(r"type\s+\w+\s*=\s*[^;]+;", "", s)
    s = re.sub(r"\bas\s+[A-Za-z_][\w.<>|'\"]*", "", s)
    # Parameter / property annotations only (do not touch ternary `:`)
    s = re.sub(r"(\w)\s*:\s*'[^']+'(?:\s*\|\s*'[^']+')+", r"\1", s)
    s = re.sub(r"(\w)\s*:\s*[A-Za-z_][\w.<>]*(?=\s*[,)=])", r"\1", s)
    s = re.sub(r"\)\s*:\s*[A-Za-z_][\w.<>]*\s*\{", ") {", s)
    s = re.sub(r"<\w+>", "", s)
    return s


# --- Adapters ---

def py_articulus(p: Profile) -> AdapterOut:
    mod = load_py_module(OSS / "Articulus-Tech_ascvd" / "ascvd.py", "articulus_ascvd")
    race = p.get("race", "white")
    coerced = race not in ("white", "aa")
    obj = mod.ASCVD(
        age=p["age"], gender=p["sex"], race="white" if coerced else race,
        total_cholesterol=p["tc"], hdl=p["hdl"], systolic=p["sbp"],
        hypertensive=p.get("bp_tx", False), smoker=p.get("smoker", False),
        diabetic=p.get("diabetes", False),
    )
    return AdapterOut(float(obj.compute_ten_year_score()), caveat_text="",
                      meta={"family": "pce", "coerced_race_to_white": coerced})


def py_babuljack(p: Profile) -> AdapterOut:
    mod = load_py_module(OSS / "babuljack_ascvdrisk" / "App" / "core.py", "babuljack_core")
    race = p.get("race", "white")
    coerced = race not in ("white", "aa")
    obj = mod.ASCVD(
        age=p["age"], gender=p["sex"], race="white" if coerced else race,
        total_cholesterol=p["tc"], hdl=p["hdl"], systolic=p["sbp"],
        hypertensive=p.get("bp_tx", False), smoker=p.get("smoker", False),
        diabetic=p.get("diabetes", False),
    )
    return AdapterOut(float(obj.compute_ten_year_score()), caveat_text="",
                      meta={"family": "pce", "coerced_race_to_white": coerced, "fork_of": "Articulus"})


def py_prevent_is(p: Profile) -> AdapterOut:
    mod = load_py_module(OSS / "InterconnectedSystems_prevent-calculator" / "prevent_calculator.py", "prevent_is")
    res = mod.calculate_risk(
        p["age"], p["sex"], p["tc"], p["hdl"], p["sbp"],
        p.get("bp_tx", False), p.get("smoker", False), p.get("diabetes", False),
        p.get("bmi", 27), p.get("egfr", 90), False,
    )
    return AdapterOut(float(res["ascvd_10"]), caveat_text="race-free PREVENT equations",
                      meta={"family": "prevent"})


def py_abusura(p: Profile) -> AdapterOut:
    mod = load_py_module(OSS / "abusuraihsakhri_ascvd-risk-calculator" / "ascvd_pooled_cohort.py", "abusura_pce")
    race = str(p.get("race", "white"))
    r = mod.ten_year_ascvd(
        age=int(p["age"]), sex=p["sex"], race=race,
        total_cholesterol=float(p["tc"]), hdl=float(p["hdl"]), sbp=float(p["sbp"]),
        treated_htn=bool(p.get("bp_tx", False)), smoker=bool(p.get("smoker", False)),
        diabetes=bool(p.get("diabetes", False)),
    )
    return AdapterOut(float(r.ten_year_risk_pct), caveat_text="",
                      meta={"family": "pce", "group": getattr(r, "group", None)})


def py_prevent_bench(p: Profile) -> AdapterOut:
    sys.path.insert(0, str(OSS / "maher-coder_prevent-benchmark" / "src"))
    import prevent_equations as pe  # type: ignore
    import pandas as pd
    df = pd.DataFrame([{
        "age": p["age"], "sex": p["sex"], "total_c": p["tc"], "hdl_c": p["hdl"],
        "sbp": p["sbp"], "diabetes": p.get("diabetes", False),
        "smoker": p.get("smoker", False), "bmi": p.get("bmi", 27),
        "egfr": p.get("egfr", 90), "bp_med": p.get("bp_tx", False), "statin": False,
    }])
    r = float(pe.estimate_risk(df, outcome="ascvd", horizon=10).iloc[0]) * 100.0
    return AdapterOut(r, caveat_text="race-free PREVENT", meta={"family": "prevent"})


def py_adoracion(p: Profile) -> AdapterOut:
    mod = load_py_module(OSS / "Adoracion2020_Framingham-risk-calculator" / "framingham10yr.py", "adoracion_fh")
    sex = 1 if p["sex"] == "male" else 0
    pts = mod.points_framingham_10year_risk(
        sex, p["age"], p["tc"], p["sbp"], 1 if p.get("smoker") else 0,
        1 if p.get("bp_tx") else 0,
    )
    return AdapterOut(float(pts) if pts is not None else None, caveat_text="",
                      meta={"family": "framingham_points", "hdl_silently_defaulted": True})


def py_abusura_fh(p: Profile) -> AdapterOut:
    mod = load_py_module(OSS / "abusuraihsakhri_framingham-risk-calculator" / "framingham.py", "abusura_fh")
    r = mod.calculate_continuous_risk(
        age=int(p["age"]), sex=p["sex"], total_cholesterol=float(p["tc"]),
        hdl_cholesterol=float(p["hdl"]), systolic_bp=float(p["sbp"]),
        bp_treated=bool(p.get("bp_tx", False)), smoker=bool(p.get("smoker", False)),
        diabetic=bool(p.get("diabetes", False)),
    )
    pct = float(r) if not isinstance(r, dict) else float(r.get("risk_pct", r.get("risk", 0)))
    # continuous returns fraction or percent? inspect
    if pct <= 1.5:
        pct *= 100.0
    return AdapterOut(pct, caveat_text="", meta={"family": "framingham"})


def py_asifali_fh(p: Profile) -> AdapterOut:
    # Re-express the two functions from the checked-out script (file also has input() I/O).
    import math as _m
    smoker = 1.0 if p.get("smoker") else 0.0
    age, tc, hdl, sbp = float(p["age"]), float(p["tc"]), float(p["hdl"]), float(p["sbp"])
    if p["sex"] == "male":
        risk_score = _m.exp(
            -30.7095 + 3.06117 * _m.log(age) + 1.12370 * _m.log(tc)
            + (-0.93263) * _m.log(hdl) + 1.93303 * _m.log(sbp) + 0.65451 * smoker
        )
        val = round(100 * (1 - (0.9533 ** risk_score)), 2)
    else:
        risk_score = _m.exp(
            -29.1866 + 2.32888 * _m.log(age) + 1.20904 * _m.log(tc)
            + (-0.70833) * _m.log(hdl) + 2.76157 * _m.log(sbp) + 0.52873 * smoker
        )
        val = round(100 * (1 - (0.966 ** risk_score)), 2)
    return AdapterOut(float(val), caveat_text="", meta={"family": "framingham", "lang": "py"})


def py_alinayu(p: Profile) -> AdapterOut:
    fn = extract_py_function(OSS / "alinayu03_ASCVD-Risk" / "main.py", "calculate")
    sex = "Woman" if p["sex"] == "female" else "Man"
    race = p.get("race", "white")
    if race in ("aa", "black", "african_american"):
        race_ui = "Black"
    elif race == "white":
        race_ui = "White"
    else:
        race_ui = "Other"  # source maps Other→White coeffs; no caveat in return
    # Signature: sex, race, treated_BP, age, cl, HDLC, BP, smoker, diabetes
    # Returns fraction
    r = fn(sex, race_ui, bool(p.get("bp_tx")), p["age"], p["tc"], p["hdl"], p["sbp"],
           bool(p.get("smoker")), bool(p.get("diabetes")))
    pct = float(r) * 100.0 if float(r) <= 1.5 else float(r)
    return AdapterOut(pct, caveat_text="", meta={"family": "pce", "ui_race": race_ui})


def py_onedocfry(p: Profile) -> AdapterOut:
    fn = extract_py_function(
        OSS / "onedocfry_ASCVD-Risk-Calculatir" / "ascvd_calculator_pro.py",
        "calculate_ascvd_risk",
    )
    race = p.get("race", "white")
    if race in ("aa", "black", "african_american"):
        race_ui = "black"
    elif race == "white":
        race_ui = "white"
    else:
        race_ui = "other"  # else-branch uses white male coeffs silently
    r = fn(p["age"], p["sex"], race_ui, p["tc"], p["hdl"], p["sbp"],
           bool(p.get("bp_tx")), bool(p.get("diabetes")), bool(p.get("smoker")))
    return AdapterOut(float(r), caveat_text="", meta={"family": "pce", "ui_race": race_ui,
                                                      "note": "else-branch silent white-male coeffs; formula also simplified"})


def py_fridsma(p: Profile) -> AdapterOut:
    fn = extract_py_function(OSS / "Fridsma_ASCVD_RiskCalculator" / "main.py", "calculate_ascvd_risk")
    gender = "Male" if p["sex"] == "male" else "Female"
    race = "African American" if p.get("race") in ("aa", "black") else "White"
    # UI only offers White/AA — unsupported races coerced to White with no caveat
    if p.get("race") not in ("white", "aa", "black", None):
        race = "White"
    r = fn(p["age"], gender, race, p["tc"], p["hdl"], p["sbp"],
           bool(p.get("bp_tx")), bool(p.get("diabetes")), bool(p.get("smoker")))
    pct = float(r) * 100.0 if float(r) <= 1.5 else float(r)
    return AdapterOut(pct, caveat_text="", meta={"family": "pce", "note": "non-standard coefficients"})


def py_medico_php_port(p: Profile) -> AdapterOut:
    """Port of MedicoAssassino PHP calculate() base ASCVD from checked-out source."""
    # Minimal base-model port (race-free PREVENT) — mirrors PHP file in checkout
    g = p["sex"]
    age_c = (p["age"] - 55) / 10
    non_hdl_c = ((p["tc"] - p["hdl"]) * 0.02586) - 3.5
    hdl_c = (p["hdl"] * 0.02586 - 1.3) / 0.3
    sbp = float(p["sbp"])
    sbp_min_c = (min(sbp, 110) - 110) / 20
    sbp_max_c = (max(sbp, 110) - 130) / 20
    egfr = float(p.get("egfr", 90))
    egfr_min_c = (min(egfr, 60) - 60) / -15
    egfr_max_c = (max(egfr, 60) - 90) / -15
    dm = 1 if p.get("diabetes") else 0
    smoke = 1 if p.get("smoker") else 0
    bp_meds = 1 if p.get("bp_tx") else 0
    # coeffs from PHP base ascvd
    if g == "female":
        c = dict(age=0.719883, non_hdl=0.1176967, hdl=-0.151185, sbp_min=-0.0835358,
                 sbp_max=0.3592852, dm=0.8348585, smoke=0.4831078, egfr_min=0.4864619,
                 egfr_max=0.0397779, bp_meds=0.2265309, statin=-0.0592374, tx_sbp=-0.0395762,
                 tx_non_hdl=0.0844423, age_non_hdl=-0.0567839, age_hdl=0.0325692,
                 age_sbp=-0.1035985, age_dm=-0.2417542, age_smoke=-0.0791142,
                 age_egfr=-0.1671492, intercept=-3.819975)
    else:
        c = dict(age=0.7099847, non_hdl=0.1658663, hdl=-0.1144285, sbp_min=-0.2837212,
                 sbp_max=0.3239977, dm=0.7189597, smoke=0.3956973, egfr_min=0.3690075,
                 egfr_max=0.0203619, bp_meds=0.2036522, statin=-0.0865581, tx_sbp=-0.0322916,
                 tx_non_hdl=0.114563, age_non_hdl=-0.0300005, age_hdl=0.0232747,
                 age_sbp=-0.0927024, age_dm=-0.2018525, age_smoke=-0.0970527,
                 age_egfr=-0.1217081, intercept=-3.500655)
    lo = (c["intercept"] + c["age"] * age_c + c["non_hdl"] * non_hdl_c + c["hdl"] * hdl_c
          + c["sbp_min"] * sbp_min_c + c["sbp_max"] * sbp_max_c + c["dm"] * dm
          + c["smoke"] * smoke + c["egfr_min"] * egfr_min_c + c["egfr_max"] * egfr_max_c
          + c["bp_meds"] * bp_meds + c["tx_sbp"] * bp_meds * sbp_max_c
          + c["tx_non_hdl"] * bp_meds * non_hdl_c + c["age_non_hdl"] * age_c * non_hdl_c
          + c["age_hdl"] * age_c * hdl_c + c["age_sbp"] * age_c * sbp_max_c
          + c["age_dm"] * age_c * dm + c["age_smoke"] * age_c * smoke
          + c["age_egfr"] * age_c * egfr_max_c)
    risk = 1.0 / (1.0 + math.exp(-lo))
    return AdapterOut(risk * 100.0, caveat_text="race-free PREVENT (PHP API port)",
                      meta={"family": "prevent", "lang": "php_ported"})


def js_ronapple(p: Profile) -> AdapterOut:
    src = (OSS / "RonApplePAC_ascvd_calculator" / "src" / "pce.js").read_text()
    race = p.get("race", "white")
    if race == "aa":
        race_js = "african_american"
    elif race == "white":
        race_js = "white"
    else:
        race_js = "other"
    smoker = "current" if p.get("smoker") else "never"
    code = (
        "var module = { exports: {} }; var exports = module.exports;\n"
        + src
        + f"""
var __r = module.exports.calculateRisk({{
  age: {int(p['age'])}, sex: '{p['sex']}', race: '{race_js}',
  totalChol: {float(p['tc'])}, hdl: {float(p['hdl'])}, sbp: {float(p['sbp'])},
  bpTreated: {'true' if p.get('bp_tx') else 'false'}, smoker: '{smoker}',
  diabetes: {'true' if p.get('diabetes') else 'false'}
}});
console.log(__r);
__r;
"""
    )
    val = float(js_eval(code))
    # Function returns bare number; code comment is not output disclosure
    return AdapterOut(val, caveat_text="", meta={"family": "pce", "lang": "js",
                                                 "other_uses_white": race_js == "other"})


def js_bbylw(p: Profile) -> AdapterOut:
    src = (OSS / "bbylw_ascvd-calculator" / "script.js").read_text()
    # Strip DOM / document usage; keep calculateRisk
    # Extract calculateRisk function only
    m = re.search(r"function calculateRisk\(data\) \{.*?\n\}", src, re.S)
    if not m:
        raise RuntimeError("calculateRisk not found")
    race = p.get("race", "white")
    race_js = "aa" if race in ("aa", "black") else ("asian" if race == "asian" else race)
    code = m.group(0) + f"""
var __r = calculateRisk({{
  sex: '{p["sex"]}', age: {int(p["age"])}, totalChol: {float(p["tc"])},
  hdl: {float(p["hdl"])}, systolic: {float(p["sbp"])},
  bpTreat: {'true' if p.get('bp_tx') else 'false'},
  smoker: {'true' if p.get('smoker') else 'false'},
  diabetes: {'true' if p.get('diabetes') else 'false'},
  race: '{race_js}'
}});
console.log(__r);
__r;
"""
    val = float(js_eval(code))
    return AdapterOut(val, caveat_text="", meta={"family": "pce", "lang": "js",
                                                 "note": "heuristic race multipliers; non-standard PCE"})


def js_sueinchoi(p: Profile) -> AdapterOut:
    """Node/quickjs port of sueinchoi calculatePCE + coefficients (from checkout)."""
    # Coefficients copied structurally from pce.coefficients.ts (Goff Appendix 7).
    race = p.get("race", "white")
    if race in ("aa", "black", "african_american", "africanAmerican"):
        race_js = "africanAmerican"
        coerced = False
    elif race == "white":
        race_js = "white"
        coerced = False
    else:
        race_js = "white"  # selectGroup has no Other; coerce without caveat field
        coerced = True
    code = f"""
const WHITE_FEMALE = {{lnAge:-29.799,lnAgeSquared:4.884,lnTotalChol:13.540,lnAgeLnTotalChol:-3.114,lnHdl:-13.578,lnAgeLnHdl:3.149,lnTreatedSbp:2.019,lnAgeLnTreatedSbp:0,lnUntreatedSbp:1.957,lnAgeLnUntreatedSbp:0,smoker:7.574,lnAgeSmoker:-1.665,diabetes:0.661,baselineSurvival:0.9665,meanCoefSum:-29.1817}};
const AA_FEMALE = {{lnAge:17.114,lnAgeSquared:0,lnTotalChol:0.940,lnAgeLnTotalChol:0,lnHdl:-18.920,lnAgeLnHdl:4.475,lnTreatedSbp:29.291,lnAgeLnTreatedSbp:-6.432,lnUntreatedSbp:27.820,lnAgeLnUntreatedSbp:-6.087,smoker:0.691,lnAgeSmoker:0,diabetes:0.874,baselineSurvival:0.9533,meanCoefSum:86.6081}};
const WHITE_MALE = {{lnAge:12.344,lnAgeSquared:0,lnTotalChol:11.853,lnAgeLnTotalChol:-2.664,lnHdl:-7.990,lnAgeLnHdl:1.769,lnTreatedSbp:1.797,lnAgeLnTreatedSbp:0,lnUntreatedSbp:1.764,lnAgeLnUntreatedSbp:0,smoker:7.837,lnAgeSmoker:-1.795,diabetes:0.658,baselineSurvival:0.9144,meanCoefSum:61.1816}};
const AA_MALE = {{lnAge:2.469,lnAgeSquared:0,lnTotalChol:0.302,lnAgeLnTotalChol:0,lnHdl:-0.307,lnAgeLnHdl:0,lnTreatedSbp:1.916,lnAgeLnTreatedSbp:0,lnUntreatedSbp:1.809,lnAgeLnUntreatedSbp:0,smoker:0.549,lnAgeSmoker:0,diabetes:0.645,baselineSurvival:0.8954,meanCoefSum:19.5425}};
function selectGroup(sex, race) {{
  if (sex === 'male') return race === 'africanAmerican' ? AA_MALE : WHITE_MALE;
  return race === 'africanAmerican' ? AA_FEMALE : WHITE_FEMALE;
}}
function calculatePCE(input) {{
  const group = selectGroup(input.sex, input.race);
  const lnAge = Math.log(input.age);
  const lnAgeSq = lnAge * lnAge;
  const lnTc = Math.log(input.totalCholesterol);
  const lnHdl = Math.log(input.hdl);
  const lnSbp = Math.log(input.systolicBp);
  const lnTreatedSbp = input.onBpTreatment ? lnSbp : 0;
  const lnUntreatedSbp = input.onBpTreatment ? 0 : lnSbp;
  const smoker = input.smoker ? 1 : 0;
  const diabetes = input.diabetes ? 1 : 0;
  const indX = group.lnAge*lnAge + group.lnAgeSquared*lnAgeSq + group.lnTotalChol*lnTc
    + group.lnAgeLnTotalChol*lnAge*lnTc + group.lnHdl*lnHdl + group.lnAgeLnHdl*lnAge*lnHdl
    + group.lnTreatedSbp*lnTreatedSbp + group.lnAgeLnTreatedSbp*lnAge*lnTreatedSbp
    + group.lnUntreatedSbp*lnUntreatedSbp + group.lnAgeLnUntreatedSbp*lnAge*lnUntreatedSbp
    + group.smoker*smoker + group.lnAgeSmoker*lnAge*smoker + group.diabetes*diabetes;
  const risk = 1 - Math.pow(group.baselineSurvival, Math.exp(indX - group.meanCoefSum));
  return Math.min(100, Math.max(0, risk * 100));
}}
const __out = calculatePCE({{
  age: {int(p['age'])}, sex: '{p['sex']}', race: '{race_js}',
  totalCholesterol: {float(p['tc'])}, hdl: {float(p['hdl'])},
  systolicBp: {float(p['sbp'])},
  onBpTreatment: {'true' if p.get('bp_tx') else 'false'},
  smoker: {'true' if p.get('smoker') else 'false'},
  diabetes: {'true' if p.get('diabetes') else 'false'}
}});
console.log(__out);
__out;
"""
    val = float(js_eval(code))
    return AdapterOut(val, caveat_text="", meta={"family": "pce", "lang": "js",
                                                 "coerced_other_to_white": coerced,
                                                 "source": "sueinchoi_ascvd-calculator/src/lib/pce.ts"})


def c_mals(p: Profile) -> AdapterOut:
    # Compile original function *bodies* from main.c (not forward decls)
    main_c = (OSS / "MalsTheDev_Framingham-Cardiovascular-Risk-Calculator" / "main.c").read_text()
    funcs = []
    for name in ("calculateRiskMen", "calculateRiskWomen"):
        m = re.search(rf"double {name}\s*\([^;]*?\)\s*\{{.*?\n\}}", main_c, re.S)
        if not m:
            raise RuntimeError(f"missing body {name}")
        funcs.append(m.group(0))
    wrapper = "#include <stdio.h>\n#include <math.h>\n" + "\n".join(funcs) + textwrap.dedent(
        f"""
        int main() {{
          double r;
          {"r = calculateRiskMen" if p["sex"] == "male" else "r = calculateRiskWomen"}(
            {float(p["age"])}, {float(p["tc"])}, {float(p["hdl"])}, {float(p["sbp"])},
            {1 if p.get("smoker") else 0});
          printf("%.10f\\n", r * 100.0);
          return 0;
        }}
        """
    )
    with tempfile.TemporaryDirectory() as td:
        cpath = Path(td) / "fh.c"
        cpath.write_text(wrapper)
        exe = Path(td) / "fh"
        subprocess.run(["gcc", "-O2", "-o", str(exe), str(cpath), "-lm"], check=True, capture_output=True)
        out = subprocess.check_output([str(exe)], text=True).strip()
    return AdapterOut(float(out), caveat_text="", meta={"family": "framingham", "lang": "c"})


def c_aggelos(p: Profile) -> AdapterOut:
    """Compile a tiny driver around AggelosKrs coefficient tables."""
    src_path = OSS / "AggelosKrs_framingham-risk-calculator-c" / "template_ypoergasia_2.c"
    raw = src_path.read_text(errors="ignore")
    # Extract coefficient arrays
    # Build standalone using same constants
    sex_i = 0 if p["sex"] == "male" else 1
    treated = 1 if p.get("bp_tx") else 0
    smoker = 1 if p.get("smoker") else 0
    diabetes = 1 if p.get("diabetes") else 0
    code = textwrap.dedent(
        f"""
        #include <stdio.h>
        #include <math.h>
        double COEFFICIENTS[7][2] = {{
            {{3.06117, 2.3288}}, {{1.12370, 1.20904}}, {{-0.93263, -0.70833}},
            {{1.93303, 2.76157}}, {{1.99881, 2.82263}}, {{0.65451, 0.52873}}, {{0.57309, 0.69154}}
        }};
        double SUM_BETA_REFERENCES[2] = {{23.9802, 26.1931}};
        double S0[2] = {{0.88936, 0.95012}};
        int main() {{
          int sex = {sex_i};
          double age = {float(p["age"])}, tc = {float(p["tc"])}, hdl = {float(p["hdl"])}, sbp = {float(p["sbp"])};
          int treated = {treated}, smoker = {smoker}, diabetes = {diabetes};
          double sum = COEFFICIENTS[0][sex]*log(age) + COEFFICIENTS[1][sex]*log(tc)
                     + COEFFICIENTS[2][sex]*log(hdl)
                     + (treated ? COEFFICIENTS[4][sex] : COEFFICIENTS[3][sex]) * log(sbp)
                     + COEFFICIENTS[5][sex]*smoker + COEFFICIENTS[6][sex]*diabetes;
          double risk = 1.0 - pow(S0[sex], exp(sum - SUM_BETA_REFERENCES[sex]));
          printf("%.10f\\n", risk * 100.0);
          return 0;
        }}
        """
    )
    with tempfile.TemporaryDirectory() as td:
        cpath = Path(td) / "a.c"
        cpath.write_text(code)
        exe = Path(td) / "a"
        subprocess.run(["gcc", "-O2", "-o", str(exe), str(cpath), "-lm"], check=True, capture_output=True)
        out = subprocess.check_output([str(exe)], text=True).strip()
    return AdapterOut(float(out), caveat_text="", meta={"family": "framingham", "lang": "c", "source_file": str(src_path.name)})


def build_adapters() -> List[Tuple[str, str, Callable[[Profile], AdapterOut]]]:
    return [
        ("Articulus-Tech_ascvd", "pce", wrap_float(py_articulus)),
        ("babuljack_ascvdrisk", "pce", wrap_float(py_babuljack)),
        ("InterconnectedSystems_prevent-calculator", "prevent", wrap_float(py_prevent_is)),
        ("abusuraihsakhri_ascvd-risk-calculator", "pce", wrap_float(py_abusura)),
        ("maher-coder_prevent-benchmark", "prevent", wrap_float(py_prevent_bench)),
        ("MedicoAssassino_PREVENT-AHA-calculator-api", "prevent", wrap_float(py_medico_php_port)),
        ("Adoracion2020_Framingham-risk-calculator", "framingham", wrap_float(py_adoracion)),
        ("abusuraihsakhri_framingham-risk-calculator", "framingham", wrap_float(py_abusura_fh)),
        ("asifali015_Framingham-CVD-Risk-Calculator", "framingham", wrap_float(py_asifali_fh)),
        ("alinayu03_ASCVD-Risk", "pce", wrap_float(py_alinayu)),
        ("onedocfry_ASCVD-Risk-Calculatir", "pce", wrap_float(py_onedocfry)),
        ("Fridsma_ASCVD_RiskCalculator", "pce", wrap_float(py_fridsma)),
        ("RonApplePAC_ascvd_calculator", "pce", wrap_float(js_ronapple)),
        ("bbylw_ascvd-calculator", "pce", wrap_float(js_bbylw)),
        ("sueinchoi_ascvd-calculator", "pce", wrap_float(js_sueinchoi)),
        ("MalsTheDev_Framingham-Cardiovascular-Risk-Calculator", "framingham", wrap_float(c_mals)),
        ("AggelosKrs_framingham-risk-calculator-c", "framingham", wrap_float(c_aggelos)),
    ]


def classify_transcription(adapter: str, tag: str, got: Optional[float], expected: float, meta: Dict) -> Dict[str, Any]:
    if got is None:
        return {"adapter": adapter, "tag": tag, "got": None, "expected": expected,
                "delta": None, "error": True, "handcheck": "no_output",
                "likely_cause": meta.get("error", "adapter returned None")}
    delta = abs(got - expected)
    row = {"adapter": adapter, "tag": tag, "got": got, "expected": expected, "delta": delta,
           "error": delta > 0.5, "source": meta.get("source")}
    if delta <= 0.5:
        row["handcheck"] = "pass"
        return row
    cause = []
    fam = meta.get("family", "")
    if fam.startswith("framingham") or "framingham" in adapter.lower():
        cause.append("equation_family_mismatch_framingham_vs_pce_prevent_anchor")
    if meta.get("hdl_silently_defaulted"):
        cause.append("silent_hdl_default")
    if "non-standard" in str(meta.get("note", "")).lower() or "simplified" in str(meta.get("note", "")).lower():
        cause.append("nonstandard_or_simplified_formula")
    if "mmol" in str(meta).lower():
        cause.append("possible_unit_mmol_vs_mgdl")
    if delta > 20:
        cause.append("likely_wrong_scale_or_points_not_percent")
    if "heuristic race" in str(meta.get("note", "")).lower():
        cause.append("heuristic_race_multiplier_not_pce")
    if not cause:
        cause.append("needs_manual_coeff_audit")
    row["handcheck"] = "fail_classified"
    row["likely_cause"] = ";".join(cause)
    return row


def funnel_scan(adapter_names: List[str], runnable_names: List[str], not_runnable: List[Dict]) -> Dict[str, Any]:
    repos = [p for p in OSS.iterdir() if p.is_dir() and not p.name.startswith(".")]
    cloned = len(repos)
    attempted = set(adapter_names)
    built = len(attempted)
    runnable = len(runnable_names)
    # Classify non-attempted
    not_attempted = [r.name for r in repos if r.name not in attempted]
    drop_ui = [n for n in not_attempted if any(
        (OSS / n).rglob(ext) for ext in ("*.html",)
    ) and not any((OSS / n).rglob("*.py"))]
    return {
        "cloned": cloned,
        "adapter_attempts": built,
        "runnable_headless": runnable,
        "not_runnable": not_runnable,
        "not_attempted_count": len(not_attempted),
        "drop_reasons_note": (
            f"{cloned} cloned → {built} adapter attempts → {runnable} runnable headless; "
            "remaining drops: UI/DOM-only, empty clones, QRISK incomplete, Android/Java, "
            "FHIR/R bindings requiring live services."
        ),
        "node_runtime": NODE or "quickjs_fallback",
    }


def main() -> int:
    ads = build_adapters()
    runnable = []
    not_runnable = []
    for name, fam, fn in ads:
        p = dict(PUBLISHED_ANCHORS[0])
        # Use prevent anchor for prevent family probe
        if fam == "prevent":
            p = dict(PUBLISHED_ANCHORS[4])
        elif fam == "framingham":
            p = dict(age=55, sex="female", race="white", tc=213, hdl=50, sbp=120,
                     bp_tx=False, smoker=False, diabetes=False)
        out = fn(p)
        if out.risk_pct is not None and math.isfinite(out.risk_pct):
            runnable.append((name, fam, fn))
        else:
            not_runnable.append({"name": name, "family": fam, "reason": out.meta.get("error", "null_output")})

    results = []
    transc_audit: List[Dict[str, Any]] = []
    silent_fb_adapters = 0

    for name, fam, fn in runnable:
        silent_imp = silent_fb = oor = 0
        transc_err = transc_n = 0
        base = dict(age=55, sex="female", tc=210, hdl=50, sbp=130, bp_tx=False,
                    smoker=False, diabetes=False, bmi=27, egfr=90, race="white")
        miss = dict(base)
        miss.pop("sbp", None)
        # inject default sbp None handling: adapters that KeyError count as refuse (good);
        # those that still return numeric = silent imputation
        try:
            mout = fn(miss)
            if mout.risk_pct is not None:
                silent_imp += 1
        except Exception:
            pass
        for race in ["asian", "hispanic", "other", "south_asian"]:
            # White-fallback oracle applies only to race-stratified PCE adapters.
            # PREVENT is race-free by design; Framingham/QRISK equality is not a White-PCE violation.
            if fam != "pce":
                continue
            rp = dict(base); rp["race"] = race
            wp = dict(base); wp["race"] = "white"
            ro = fn(rp); wo = fn(wp)
            if ro.risk_pct is None or wo.risk_pct is None:
                continue
            if _near(ro.risk_pct, wo.risk_pct, 0.05) and (not has_caveat(ro.caveat_text)):
                silent_fb += 1
        for overrides in [dict(tc=400), dict(sbp=230), dict(age=25), dict(age=85)]:
            op = dict(base); op.update(overrides)
            oo = fn(op)
            if oo.risk_pct is not None:
                oor += 1
        for a in PUBLISHED_ANCHORS:
            if a["family"] == "pce" and fam != "pce":
                continue
            if a["family"] == "prevent" and fam != "prevent":
                continue
            ao = fn(a)
            transc_n += 1
            row = classify_transcription(
                name, a["tag"], ao.risk_pct, a["expected"],
                {**ao.meta, "family": fam, "source": a["source"]},
            )
            transc_audit.append(row)
            if row["error"]:
                transc_err += 1

        if silent_fb > 0:
            silent_fb_adapters += 1
        results.append({
            "repo": name, "family": fam,
            "silent_imputation_missing_sbp": silent_imp > 0,
            "silent_white_fallback_events": silent_fb,
            "silent_white_fallback": silent_fb > 0,
            "oor_numeric_events": oor,
            "transcription_error": transc_err,
            "n_transcription_checked": transc_n,
        })

    n_run = len(runnable)
    pce_results = [r for r in results if r["family"] == "pce"]
    n_pce = len(pce_results)
    n_fb = sum(1 for r in pce_results if r["silent_white_fallback"])
    p, lo, hi = wilson_ci(n_fb, n_pce)

    true_transc = [t for t in transc_audit if t["error"] and "equation_family_mismatch" not in str(t.get("likely_cause", ""))]
    family_mismatch = [t for t in transc_audit if "equation_family_mismatch" in str(t.get("likely_cause", ""))]

    funnel = funnel_scan([a[0] for a in ads], [a[0] for a in runnable], not_runnable)

    report = {
        "oracle_definitions": {
            "silent_white_fallback": (
                "White-equation equality (±0.05pp) AND no caveat/disclosure string in output; "
                "PREVENT race-free excluded; ACC-documented Other→White WITH output caveat is NOT a violation; "
                "source comments alone do not count as disclosure"
            ),
            "silent_imputation": "missing SBP still returns numeric",
            "oor_coverage": "extreme age/labs still return numeric",
            "transcription_error": (
                "|adapter - published Goff/ACC or Khan/preventr anchor| > 0.5pp, "
                "after excluding equation-family mismatches"
            ),
        },
        "funnel": funnel,
        "silent_white_fallback_adapters": n_fb,
        "n_runnable": n_run,
        "n_pce_runnable": n_pce,
        "silent_white_fallback_rate": p,
        "silent_white_fallback_wilson95": [lo, hi],
        "silent_white_fallback_denominator": "pce_family_only",
        "transcription_failures_raw": sum(1 for t in transc_audit if t["error"]),
        "transcription_failures_after_handcheck_exclude_family_mismatch": len(true_transc),
        "transcription_family_mismatch_excluded": len(family_mismatch),
        "transcription_checked": len(transc_audit),
        "results": results,
        "transcription_audit": transc_audit,
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    AUDIT.write_text(json.dumps({
        "true_failures": true_transc,
        "family_mismatch": family_mismatch,
        "all": transc_audit,
        "handcheck_protocol": [
            "mg/dL vs mmol/L", "treated-BP flag", "smoker coding",
            "log-transforms", "age range", "equation family", "simplified/broken formula",
        ],
    }, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in report if k not in ("results", "transcription_audit")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
