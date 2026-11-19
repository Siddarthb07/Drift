#!/usr/bin/env python3
"""
NHANES 2017–March 2020 disclosure-disparity + risk-reclassification audit.

- eGFR: 2021 race-free CKD-EPI creatinine
- Survey weights (WTMECPRP) for weighted rates
- Design-based 95% CIs via stratified Taylor linearization (SDMVSTRA + SDMVPSU)
- Refusal gate decomposition by race
- Legacy vs honest band reclassification / threshold crossings / misattribution burden

Honest about construction: among PCE-scored non-White/non-AA, White fallback = 1.0 by legacy design.
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from risk_engine import compute_risk_scores  # noqa: E402

NHANES = ROOT / "data" / "nhanes"
OUT = ROOT / "docs" / "facct" / "nhanes_coverage_audit.json"
TABLES = ROOT / "docs" / "facct" / "tables.json"
SEED = 42
MAX_N = None  # full eligible sample; set e.g. 4000 only for quick local runs

RACE_MAP = {
    1: "hispanic",
    2: "hispanic",
    3: "white",
    4: "aa",
    6: "asian_nhanes",
    7: "multiracial",
}

# Treatment / risk-band cutpoints (percent)
CUT_5 = 5.0
CUT_7_5 = 7.5
CUT_20 = 20.0

# Critical values of Student's t (two-sided 95%) for common df; interpolate.
_T975 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    12: 2.179, 15: 2.131, 20: 2.086, 24: 2.064, 25: 2.060,
    30: 2.042, 40: 2.021, 50: 2.009, 60: 2.000, 120: 1.980,
    10_000: 1.960,
}


def _t_crit_95(df: int) -> float:
    if df < 1:
        return float("nan")
    if df in _T975:
        return _T975[df]
    keys = sorted(_T975)
    if df > keys[-1]:
        return _T975[keys[-1]]
    lo = max(k for k in keys if k <= df)
    hi = min(k for k in keys if k >= df)
    if lo == hi:
        return _T975[lo]
    w = (df - lo) / (hi - lo)
    return _T975[lo] * (1 - w) + _T975[hi] * w


def _read(name: str):
    path = NHANES / f"{name}.xpt"
    if not path.exists() or path.stat().st_size < 50_000:
        raise FileNotFoundError(f"Missing or truncated {path}")
    return pd.read_sas(path, format="xport")


def _egfr_ckd_epi_2021(scr_mgdl: float, age: float, female: bool) -> float:
    """2021 CKD-EPI creatinine (race-free)."""
    if scr_mgdl is None or np.isnan(scr_mgdl) or scr_mgdl <= 0:
        return float("nan")
    kappa = 0.7 if female else 0.9
    alpha = -0.241 if female else -0.302
    scr_k = scr_mgdl / kappa
    egfr = 142.0 * (min(scr_k, 1.0) ** alpha) * (max(scr_k, 1.0) ** -1.200) * (0.9938 ** age)
    if female:
        egfr *= 1.012
    return float(egfr)


def _band(pct):
    if pct is None:
        return None
    if pct < 5:
        return "<5%"
    if pct < 7.5:
        return "5–7.5%"
    if pct < 20:
        return "7.5–20%"
    return "≥20%"


def _crosses_up(lo_pct: float, hi_pct: float, cut: float) -> bool:
    """True if lo is strictly below cut and hi is at/above cut (threshold crossed upward)."""
    return lo_pct < cut <= hi_pct


def build_frame():
    demo = _read("P_DEMO")
    bpx = _read("P_BPXO")
    bmx = _read("P_BMX")
    hdl = _read("P_HDL")
    tchol = _read("P_TCHOL")
    bio = _read("P_BIOPRO")
    extras = []
    for name in ("P_SMQ", "P_DIQ", "P_BPQ"):
        p = NHANES / f"{name}.xpt"
        if p.exists() and p.stat().st_size > 50_000:
            extras.append(_read(name))
    df = demo.merge(bpx, on="SEQN", how="left")
    df = df.merge(bmx, on="SEQN", how="left")
    df = df.merge(hdl, on="SEQN", how="left")
    df = df.merge(tchol, on="SEQN", how="left")
    df = df.merge(bio, on="SEQN", how="left")
    for ex in extras:
        df = df.merge(ex, on="SEQN", how="left")
    df = df[(df["RIDAGEYR"] >= 30) & (df["RIDAGEYR"] <= 79)].copy()
    df = df[df["RIAGENDR"].isin([1, 2])]
    df = df[df["RIDRETH3"].isin(RACE_MAP.keys())]
    return df


def row_to_user(row):
    age = float(row["RIDAGEYR"])
    female = int(row["RIAGENDR"]) == 2
    sex = "female" if female else "male"
    race = RACE_MAP[int(row["RIDRETH3"])]
    height = float(row["BMXHT"]) if row.get("BMXHT") == row.get("BMXHT") else None
    weight = float(row["BMXWT"]) if row.get("BMXWT") == row.get("BMXWT") else None
    if height is None or weight is None:
        # Do not invent 170/70 — leave missing; engine will refuse missing BMI
        pass
    sbps = [row.get(c) for c in ("BPXOSY1", "BPXOSY2", "BPXOSY3") if c in row.index]
    sbps = [float(x) for x in sbps if x == x and x is not None]
    sbp = float(np.mean(sbps)) if sbps else None
    tc = float(row["LBXTC"]) if row.get("LBXTC") == row.get("LBXTC") else None
    hdlv = float(row["LBDHDD"]) if row.get("LBDHDD") == row.get("LBDHDD") else None
    scr = float(row["LBXSCR"]) if row.get("LBXSCR") == row.get("LBXSCR") else None
    egfr = _egfr_ckd_epi_2021(scr, age, female) if scr else float("nan")
    smoker = False
    if "SMQ040" in row.index and row.get("SMQ040") == row.get("SMQ040"):
        try:
            smoker = int(row["SMQ040"]) in (1, 2)
        except (TypeError, ValueError):
            smoker = False
    diabetes = False
    if "DIQ010" in row.index and row.get("DIQ010") == row.get("DIQ010"):
        try:
            diabetes = int(row["DIQ010"]) == 1
        except (TypeError, ValueError):
            diabetes = False
    bp_meds = False
    if "BPQ050A" in row.index and row.get("BPQ050A") == row.get("BPQ050A"):
        try:
            bp_meds = int(row["BPQ050A"]) == 1
        except (TypeError, ValueError):
            bp_meds = False
    # 2017–March 2020 pre-pandemic exam weight is WTMECPRP (not WTMEC4YR)
    wt = None
    for col in ("WTMECPRP", "WTMEC2YR", "WTMEC4YR"):
        if col in row.index and row.get(col) == row.get(col) and float(row[col]) > 0:
            wt = float(row[col])
            break
    if wt is None:
        wt = 1.0

    strata = None
    psu = None
    if "SDMVSTRA" in row.index and row.get("SDMVSTRA") == row.get("SDMVSTRA"):
        strata = int(row["SDMVSTRA"])
    if "SDMVPSU" in row.index and row.get("SDMVPSU") == row.get("SDMVPSU"):
        psu = int(row["SDMVPSU"])

    user = {
        "age": age, "sex": sex, "sex_for_equation": sex,
        "height": height, "weight": weight,
        "waist_cm": float(row["BMXWAIST"]) if row.get("BMXWAIST") == row.get("BMXWAIST") else None,
        "systolic": sbp, "race": race,
        "smoking_status": "current" if smoker else "never",
        "bp_medication": int(bp_meds), "existing_diabetes": int(diabetes),
        "high_glucose_history": 0, "family_history_diabetes": 0,
        "family_history_cancer": 0, "alcohol_per_week": 0, "region": "global",
    }
    labs = {}
    if tc is not None:
        labs["total_cholesterol"] = tc
    if hdlv is not None:
        labs["hdl_cholesterol"] = hdlv
    if egfr == egfr:
        labs["egfr"] = egfr
    meta = {
        "has_sbp": sbp is not None,
        "has_lipids": tc is not None and hdlv is not None,
        "has_egfr": egfr == egfr,
        "complete": sbp is not None and tc is not None and hdlv is not None and egfr == egfr,
        "race": race,
        "wt": wt,
        "strata": strata,
        "psu": psu,
        "bmi": (weight / ((height / 100) ** 2)) if height and weight else None,
    }
    return user, labs, meta


def _honest_shows(hc):
    return (
        not hc.get("refused")
        and (
            hc.get("risk_pct") is not None
            or hc.get("risk_band_label")
            or hc.get("risk_pct_exact") is not None
        )
    )


def _exact_pct(block):
    if block.get("risk_pct") is not None:
        return float(block["risk_pct"])
    if block.get("risk_pct_exact") is not None:
        return float(block["risk_pct_exact"])
    return None


def _design_meta_method() -> dict:
    return {
        "estimator": "stratified_taylor_linearization_ratio",
        "design": "NHANES SDMVSTRA + SDMVPSU, with-replacement PSUs within strata",
        "weight": "WTMECPRP",
        "libraries": {
            "samplics": False,
            "statsmodels": False,
            "note": "Pure-numpy stratified Taylor; no samplics/statsmodels installed",
        },
        "formula": (
            "R = Y/W with Y=sum w*y, W=sum w over domain. "
            "PSU totals y_hi, w_hi; e_hi=(y_hi - R*w_hi)/W; "
            "Var(R)=sum_h [n_h/(n_h-1)] * sum_i (e_hi - mean_e_h)^2. "
            "Singleton strata (n_h=1) contribute 0 (conservative skip). "
            "CI uses Student-t with df = (#PSUs with any domain mass) - (#strata with >=2 PSUs)."
        ),
        "ci_level": 0.95,
        "fallback_if_unavailable": "leave_one_PSU_out_jackknife (not used when Taylor succeeds)",
    }


def stratified_taylor_rate(records: list[dict], y_key: str, domain_key: str | None = None) -> dict:
    """
    Design-based weighted rate with stratified Taylor SE / 95% CI.

    records: dicts with wt, strata, psu, y_key (0/1), optional domain_key (bool).
    Domain estimation zeros out non-domain persons (still keeps PSU structure).
    """
    method = _design_meta_method()
    # Aggregate to PSU totals within domain
    # strata -> psu -> {y, w}
    psu_tot: dict[int, dict[int, dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: {"y": 0.0, "w": 0.0}))
    all_psus: dict[int, set[int]] = defaultdict(set)

    n_domain = 0
    for r in records:
        strata, psu, wt = r.get("strata"), r.get("psu"), float(r.get("wt") or 0.0)
        if strata is None or psu is None or wt <= 0:
            continue
        all_psus[int(strata)].add(int(psu))
        in_domain = True if domain_key is None else bool(r.get(domain_key))
        if not in_domain:
            # Ensure PSU slot exists even if empty in domain
            _ = psu_tot[int(strata)][int(psu)]
            continue
        y = float(r.get(y_key) or 0.0)
        psu_tot[int(strata)][int(psu)]["y"] += wt * y
        psu_tot[int(strata)][int(psu)]["w"] += wt
        n_domain += 1

    Y = 0.0
    W = 0.0
    for h, psus in psu_tot.items():
        for i, tot in psus.items():
            Y += tot["y"]
            W += tot["w"]

    if W <= 0:
        return {
            "estimate": None,
            "se": None,
            "ci95": [None, None],
            "df": None,
            "n_domain": n_domain,
            "method": method,
            "note": "empty domain",
        }

    R = Y / W
    var = 0.0
    n_psu_used = 0
    n_strata_ge2 = 0
    singleton_strata = 0

    for h, psu_ids in all_psus.items():
        # Include every design PSU in the stratum (zeros if no domain mass)
        e_list = []
        for i in sorted(psu_ids):
            tot = psu_tot[h].get(i, {"y": 0.0, "w": 0.0})
            e_list.append((tot["y"] - R * tot["w"]) / W)
        n_h = len(e_list)
        if n_h < 2:
            singleton_strata += 1
            continue
        n_strata_ge2 += 1
        n_psu_used += n_h
        mean_e = sum(e_list) / n_h
        ss = sum((e - mean_e) ** 2 for e in e_list)
        var += (n_h / (n_h - 1)) * ss

    se = math.sqrt(max(var, 0.0))
    df = max(n_psu_used - n_strata_ge2, 1) if n_strata_ge2 else 0
    tcrit = _t_crit_95(df) if df else float("nan")
    half = tcrit * se if tcrit == tcrit else float("nan")
    lo = max(0.0, R - half) if half == half else None
    hi = min(1.0, R + half) if half == half else None

    return {
        "estimate": round(R, 6),
        "se": round(se, 6),
        "ci95": [None if lo is None else round(lo, 6), None if hi is None else round(hi, 6)],
        "df": df,
        "t_crit": None if tcrit != tcrit else round(tcrit, 4),
        "n_domain": n_domain,
        "n_psu": n_psu_used,
        "n_strata_ge2": n_strata_ge2,
        "singleton_strata_skipped": singleton_strata,
        "method": method,
    }


def jackknife_leave_one_psu(records: list[dict], y_key: str, domain_key: str | None = None) -> dict:
    """Stratified delete-one-PSU jackknife for a weighted rate (backup estimator)."""
    by_h: dict[int, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in records:
        strata, psu = r.get("strata"), r.get("psu")
        if strata is None or psu is None:
            continue
        by_h[int(strata)][int(psu)].append(r)

    def _rate(recs):
        Y = W = 0.0
        for r in recs:
            if domain_key is not None and not r.get(domain_key):
                continue
            wt = float(r.get("wt") or 0.0)
            if wt <= 0:
                continue
            Y += wt * float(r.get(y_key) or 0.0)
            W += wt
        return None if W <= 0 else Y / W

    full = _rate(records)
    if full is None:
        return {"estimate": None, "se": None, "ci95": [None, None], "method": "leave_one_PSU_out_jackknife"}

    # Collect replicate rates
    reps = []
    for h, psus in by_h.items():
        n_h = len(psus)
        if n_h < 2:
            continue
        for drop_i in psus:
            keep = []
            for hh, pp in by_h.items():
                for ii, recs in pp.items():
                    if hh == h and ii == drop_i:
                        continue
                    # Within-stratum reweight: multiply remaining PSUs in h by n_h/(n_h-1)
                    if hh == h:
                        for r in recs:
                            rr = dict(r)
                            rr["wt"] = float(r["wt"]) * (n_h / (n_h - 1))
                            keep.append(rr)
                    else:
                        keep.extend(recs)
            rj = _rate(keep)
            if rj is not None:
                reps.append((h, n_h, rj))

    var = 0.0
    # Group by stratum for JK variance
    by_stratum_reps: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for h, n_h, rj in reps:
        by_stratum_reps[h].append((n_h, rj))
    for h, items in by_stratum_reps.items():
        n_h = items[0][0]
        ss = sum((n_h - 1) / n_h * (rj - full) ** 2 for n_h, rj in items)
        var += ss

    se = math.sqrt(max(var, 0.0))
    df = max(sum(len(by_h[h]) for h in by_stratum_reps) - len(by_stratum_reps), 1)
    tcrit = _t_crit_95(df)
    half = tcrit * se
    return {
        "estimate": round(full, 6),
        "se": round(se, 6),
        "ci95": [round(max(0.0, full - half), 6), round(min(1.0, full + half), 6)],
        "df": df,
        "method": {
            "estimator": "leave_one_PSU_out_jackknife",
            "design": "NHANES SDMVSTRA + SDMVPSU",
            "weight": "WTMECPRP",
            "ci_level": 0.95,
        },
    }


def _ci_block(taylor: dict) -> dict:
    return {
        "estimate": taylor.get("estimate"),
        "se": taylor.get("se"),
        "ci95": taylor.get("ci95"),
        "df": taylor.get("df"),
    }


def _rate_block(n: int, denom_n: int, wt: float, denom_wt: float) -> dict:
    """Unweighted + survey-weighted rate among a stratum denominator."""
    out = {"n": n}
    if denom_n <= 0:
        out["rate"] = None
        out["weighted_rate"] = None
        return out
    out["rate"] = round(n / denom_n, 4)
    out["weighted_rate"] = round(wt / max(denom_wt, 1e-9), 4)
    return out


def _stratum_crossing_block(thr: dict, prefix: str) -> dict:
    """
    Build honest_higher / legacy_higher blocks at 7.5 and 20 for a thr prefix
    ('' overall, 'no_fb_', 'fb_').
    Key pattern: {prefix}cross_{cut}_{dir} and wt_{prefix}cross_{cut}_{dir}.
    """
    n_key = "n_both_numeric" if prefix == "" else f"{prefix}n"
    wt_key = "wt_both" if prefix == "" else f"wt_{prefix.rstrip('_')}"
    n = int(thr[n_key])
    wt = float(thr[wt_key])
    disagree_n = thr["any_band_disagree"] if prefix == "" else thr[f"{prefix}any_disagree"]
    disagree_wt = thr["wt_any_disagree"] if prefix == "" else thr[f"wt_{prefix}any_disagree"]

    def _cross(cut_tag: str) -> dict:
        return {
            "honest_higher": _rate_block(
                thr[f"{prefix}cross_{cut_tag}_honest_higher"],
                n,
                thr[f"wt_{prefix}cross_{cut_tag}_honest_higher"],
                wt,
            ),
            "legacy_higher": _rate_block(
                thr[f"{prefix}cross_{cut_tag}_legacy_higher"],
                n,
                thr[f"wt_{prefix}cross_{cut_tag}_legacy_higher"],
                wt,
            ),
        }

    return {
        "n": n,
        "any_band_disagree": _rate_block(int(disagree_n), n, float(disagree_wt), wt),
        "crossed_7_5": _cross("7_5"),
        "crossed_20": _cross("20"),
    }


def _xpt_available() -> bool:
    demo = NHANES / "P_DEMO.xpt"
    return demo.exists() and demo.stat().st_size >= 50_000


def _sync_tables(summary: dict) -> None:
    if not TABLES.exists():
        return
    tables = json.loads(TABLES.read_text(encoding="utf-8"))
    ov = summary["overall"]
    t2 = tables.setdefault("table2_nhanes", {})
    t2["n"] = summary["n_analyzed"]
    t2["n_full_eligible"] = summary["n_full_eligible"]
    t2["seed"] = summary["seed"]
    t2["weight"] = "WTMECPRP"
    t2["overall_honest_show"] = ov["honest_show_rate"]
    t2["overall_weighted_honest_show"] = ov["weighted_honest_show_rate"]
    t2["overall_legacy_show"] = ov["legacy_show_rate"]
    t2["overall_weighted_legacy_show"] = ov["weighted_legacy_show_rate"]
    t2["band_reclass_no_fallback_white_aa"] = ov["band_reclass_no_fallback_white_aa"]
    t2["misattributed_equation_count"] = ov["misattributed_equation_count"]
    t2["band_reclassification_rate_when_both_numeric"] = ov["band_reclassification_rate_when_both_numeric"]
    t2["fallback_among_pce_scored_nonwhite"] = 1.0
    t2["weighted_honest_show_rate_age_40_79"] = ov.get("weighted_honest_show_rate_age_40_79")
    t2["weighted_legacy_show_rate_age_40_79"] = ov.get("weighted_legacy_show_rate_age_40_79")
    t2["construction_note"] = ov.get("construction_note")
    t2["audit_design"] = summary.get("audit_design")
    # Design-based CIs + threshold crossings
    if "design_based_cis" in ov:
        t2["design_based_cis"] = ov["design_based_cis"]
    if "band_threshold_crossings" in ov:
        t2["band_threshold_crossings"] = ov["band_threshold_crossings"]
    if "weighted_misattribution_rate_among_all" in ov:
        t2["weighted_misattribution_rate_among_all"] = ov["weighted_misattribution_rate_among_all"]

    by_race = {}
    mis_n = {}
    for race, v in summary["by_race"].items():
        shares = sorted(
            v["honest"]["refuse_gates_weighted_share"].items(),
            key=lambda x: -x[1],
        )[:3]
        by_race[race] = {
            "n": v["n"],
            "honest_show": v["honest"]["show_rate"],
            "weighted_show": v["honest"]["weighted_show_rate"],
            "legacy_show": v["legacy"]["show_rate"],
            "legacy_weighted_show": v["legacy"]["weighted_show_rate"],
            "misattributed_n": v["legacy"]["misattributed_equation_count"],
            "band_reclass": v["reclassification_when_both_numeric"]["band_disagree_rate"],
            "no_fallback_band_reclass": v["reclassification_when_both_numeric"].get(
                "no_fallback_band_disagree_rate"
            ),
            "top_refuse_gates_weighted_share": [[g, s] for g, s in shares],
        }
        if "weighted_show_ci95" in v["honest"]:
            by_race[race]["weighted_show_ci95"] = v["honest"]["weighted_show_ci95"]
        mis_n[race] = v["legacy"]["misattributed_equation_count"]
    t2["by_race"] = by_race
    t2["by_race_misattributed_n"] = mis_n
    TABLES.write_text(json.dumps(tables, indent=2) + "\n", encoding="utf-8")


def main():
    if not _xpt_available():
        note = {
            "status": "dry_run_xpt_missing",
            "message": (
                "NHANES XPT files missing or truncated under data/nhanes/. "
                "Design-based CI + threshold-crossing code paths are implemented in "
                "scripts/nhanes_coverage_audit.py but audit JSON was not regenerated."
            ),
            "variance_method": _design_meta_method(),
            "expected_outputs": [
                "design_based_cis for weighted show / misattribution rates",
                "band_threshold_crossings at 5 / 7.5 / 20%",
                "fallback_stratum and no_fallback_stratum crossings at 7.5 / 20%",
            ],
        }
        OUT.parent.mkdir(parents=True, exist_ok=True)
        # Do not overwrite a good prior audit; write sibling dry-run note
        dry = OUT.with_name("nhanes_coverage_audit_dry_run.json")
        dry.write_text(json.dumps(note, indent=2), encoding="utf-8")
        print(json.dumps(note, indent=2))
        return 0

    rng = np.random.default_rng(SEED)
    df = build_frame()
    full_n = len(df)
    if MAX_N is not None and len(df) > MAX_N:
        idx = rng.choice(len(df), size=MAX_N, replace=False)
        df = df.iloc[idx].copy()

    # CVD-only audit: do NOT invent a complete lifestyle diary (that would silence
    # FINDRISC/cancer missingness and inflate a multi-outcome coverage narrative).
    daily = []

    by_race = defaultdict(lambda: {
        "n": 0, "wt": 0.0, "complete": 0, "has_egfr": 0, "has_lipids": 0, "has_sbp": 0,
        "honest_show": 0, "honest_refuse": 0, "wt_honest_show": 0.0, "wt_honest_refuse": 0.0,
        "legacy_fallback": 0, "legacy_pce_scored": 0, "legacy_under40_green": 0,
        "legacy_show": 0, "wt_legacy_show": 0.0,
        "n_age_40_79": 0, "wt_age_40_79": 0.0,
        "honest_show_40_79": 0, "wt_honest_show_40_79": 0.0,
        "legacy_show_40_79": 0, "wt_legacy_show_40_79": 0.0,
        "gates": defaultdict(float), "gates_wt": defaultdict(float),
        "reclass_diff_band": 0, "reclass_n": 0, "abs_delta_sum": 0.0,
        "reclass_no_fallback_n": 0, "reclass_no_fallback_diff": 0,
        "bmi_ge_40": 0,
    })
    overall = {
        "n": 0, "wt": 0.0, "honest_show": 0, "legacy_fallback": 0, "legacy_pce_scored": 0,
        "legacy_show": 0, "wt_legacy_show": 0.0,
        "wt_honest_show": 0.0, "reclass_diff_band": 0, "reclass_n": 0,
        "reclass_no_fallback_n": 0, "reclass_no_fallback_diff": 0,
        "n_age_40_79": 0, "wt_age_40_79": 0.0,
        "honest_show_40_79": 0, "wt_honest_show_40_79": 0.0,
        "legacy_show_40_79": 0, "wt_legacy_show_40_79": 0.0,
    }

    # Per-person design records for variance + threshold analysis
    design_recs: list[dict] = []
    # Stratum counters among both-numeric: overall / fallback / no-fallback (white+AA).
    # By construction no-fallback == white_aa_no_fallback (fallback only on non-white/non-AA).
    thr = {
        "n_both_numeric": 0,
        "any_band_disagree": 0,
        "cross_7_5_honest_higher": 0,   # legacy < 7.5 <= honest
        "cross_7_5_legacy_higher": 0,   # honest < 7.5 <= legacy
        "cross_20_honest_higher": 0,
        "cross_20_legacy_higher": 0,
        "cross_5_honest_higher": 0,
        "cross_5_legacy_higher": 0,
        "no_fb_n": 0,
        "no_fb_any_disagree": 0,
        "no_fb_cross_7_5_honest_higher": 0,
        "no_fb_cross_7_5_legacy_higher": 0,
        "no_fb_cross_20_honest_higher": 0,
        "no_fb_cross_20_legacy_higher": 0,
        "fb_n": 0,
        "fb_any_disagree": 0,
        "fb_cross_7_5_honest_higher": 0,
        "fb_cross_7_5_legacy_higher": 0,
        "fb_cross_20_honest_higher": 0,
        "fb_cross_20_legacy_higher": 0,
        "wt_both": 0.0,
        "wt_any_disagree": 0.0,
        "wt_cross_7_5_honest_higher": 0.0,
        "wt_cross_7_5_legacy_higher": 0.0,
        "wt_cross_20_honest_higher": 0.0,
        "wt_cross_20_legacy_higher": 0.0,
        "wt_no_fb": 0.0,
        "wt_no_fb_any_disagree": 0.0,
        "wt_no_fb_cross_7_5_honest_higher": 0.0,
        "wt_no_fb_cross_7_5_legacy_higher": 0.0,
        "wt_no_fb_cross_20_honest_higher": 0.0,
        "wt_no_fb_cross_20_legacy_higher": 0.0,
        "wt_fb": 0.0,
        "wt_fb_any_disagree": 0.0,
        "wt_fb_cross_7_5_honest_higher": 0.0,
        "wt_fb_cross_7_5_legacy_higher": 0.0,
        "wt_fb_cross_20_honest_higher": 0.0,
        "wt_fb_cross_20_legacy_higher": 0.0,
    }

    for _, row in df.iterrows():
        try:
            user, labs, meta = row_to_user(row)
        except Exception:
            continue
        race = meta["race"]
        wt = meta["wt"] or 1.0
        b = by_race[race]
        b["n"] += 1
        b["wt"] += wt
        overall["n"] += 1
        overall["wt"] += wt
        for k in ("complete", "has_egfr", "has_lipids", "has_sbp"):
            if meta[k]:
                b[k] += 1
        if meta.get("bmi") is not None and meta["bmi"] >= 40:
            b["bmi_ge_40"] += 1

        honest = compute_risk_scores(user, daily, labs, mode="honest", username="nhanes")
        legacy = compute_risk_scores(user, daily, labs, mode="baseline", username="nhanes")
        hc = honest.get("CVD") or {}
        lc = legacy.get("CVD") or {}

        age = float(user.get("age") or 0)
        age_40_79 = 40 <= age <= 79

        honest_show = _honest_shows(hc)
        legacy_show = _honest_shows(lc)
        legacy_show_40 = legacy_show and "Under 40" not in str(lc.get("risk_category") or "")
        fallback = bool(lc.get("legacy_white_fallback"))

        if honest_show:
            b["honest_show"] += 1
            b["wt_honest_show"] += wt
            overall["honest_show"] += 1
            overall["wt_honest_show"] += wt
        else:
            b["honest_refuse"] += 1
            b["wt_honest_refuse"] += wt
            gate = hc.get("gate") or ("refused" if hc.get("refused") else "other")
            b["gates"][gate] += 1
            b["gates_wt"][gate] += wt

        pce_scored = lc.get("risk_pct") is not None
        if pce_scored:
            b["legacy_pce_scored"] += 1
            overall["legacy_pce_scored"] += 1
        if fallback:
            b["legacy_fallback"] += 1
            overall["legacy_fallback"] += 1
        if "Under 40" in str(lc.get("risk_category") or ""):
            b["legacy_under40_green"] += 1
        if legacy_show:
            b["legacy_show"] += 1
            b["wt_legacy_show"] += wt
            overall["legacy_show"] += 1
            overall["wt_legacy_show"] += wt

        # Apples-to-apples coverage: ages 40–79 (excludes legacy under-40 green "show")
        if age_40_79:
            b["n_age_40_79"] += 1
            b["wt_age_40_79"] += wt
            overall["n_age_40_79"] += 1
            overall["wt_age_40_79"] += wt
            if honest_show:
                b["honest_show_40_79"] += 1
                b["wt_honest_show_40_79"] += wt
                overall["honest_show_40_79"] += 1
                overall["wt_honest_show_40_79"] += wt
            if legacy_show_40:
                b["legacy_show_40_79"] += 1
                b["wt_legacy_show_40_79"] += wt
                overall["legacy_show_40_79"] += 1
                overall["wt_legacy_show_40_79"] += wt

        # Reclassification when both produce a numeric (honest exact vs legacy pct)
        hp = _exact_pct(hc)
        lp = _exact_pct(lc)
        band_disagree = False
        cross_flags = {}
        if hp is not None and lp is not None:
            b["reclass_n"] += 1
            overall["reclass_n"] += 1
            b["abs_delta_sum"] += abs(hp - lp)
            band_disagree = _band(hp) != _band(lp)
            if band_disagree:
                b["reclass_diff_band"] += 1
                overall["reclass_diff_band"] += 1
            no_fb = race in ("white", "aa") and not fallback
            if no_fb:
                b["reclass_no_fallback_n"] += 1
                overall["reclass_no_fallback_n"] += 1
                if band_disagree:
                    b["reclass_no_fallback_diff"] += 1
                    overall["reclass_no_fallback_diff"] += 1

            # Threshold crossings from exact percents
            c75_h = _crosses_up(lp, hp, CUT_7_5)
            c75_l = _crosses_up(hp, lp, CUT_7_5)
            c20_h = _crosses_up(lp, hp, CUT_20)
            c20_l = _crosses_up(hp, lp, CUT_20)
            c5_h = _crosses_up(lp, hp, CUT_5)
            c5_l = _crosses_up(hp, lp, CUT_5)
            cross_flags = {
                "cross_7_5_honest_higher": c75_h,
                "cross_7_5_legacy_higher": c75_l,
                "cross_20_honest_higher": c20_h,
                "cross_20_legacy_higher": c20_l,
                "cross_5_honest_higher": c5_h,
                "cross_5_legacy_higher": c5_l,
            }
            thr["n_both_numeric"] += 1
            thr["wt_both"] += wt
            if band_disagree:
                thr["any_band_disagree"] += 1
                thr["wt_any_disagree"] += wt
            for k, flag in cross_flags.items():
                if flag:
                    thr[k] += 1
                    wk = f"wt_{k}"
                    if wk in thr:
                        thr[wk] += wt
            if no_fb:
                thr["no_fb_n"] += 1
                thr["wt_no_fb"] += wt
                if band_disagree:
                    thr["no_fb_any_disagree"] += 1
                    thr["wt_no_fb_any_disagree"] += wt
                if c75_h:
                    thr["no_fb_cross_7_5_honest_higher"] += 1
                    thr["wt_no_fb_cross_7_5_honest_higher"] += wt
                if c75_l:
                    thr["no_fb_cross_7_5_legacy_higher"] += 1
                    thr["wt_no_fb_cross_7_5_legacy_higher"] += wt
                if c20_h:
                    thr["no_fb_cross_20_honest_higher"] += 1
                    thr["wt_no_fb_cross_20_honest_higher"] += wt
                if c20_l:
                    thr["no_fb_cross_20_legacy_higher"] += 1
                    thr["wt_no_fb_cross_20_legacy_higher"] += wt
            elif fallback:
                # Misattributed / legacy White fallback among both-numeric
                thr["fb_n"] += 1
                thr["wt_fb"] += wt
                if band_disagree:
                    thr["fb_any_disagree"] += 1
                    thr["wt_fb_any_disagree"] += wt
                if c75_h:
                    thr["fb_cross_7_5_honest_higher"] += 1
                    thr["wt_fb_cross_7_5_honest_higher"] += wt
                if c75_l:
                    thr["fb_cross_7_5_legacy_higher"] += 1
                    thr["wt_fb_cross_7_5_legacy_higher"] += wt
                if c20_h:
                    thr["fb_cross_20_honest_higher"] += 1
                    thr["wt_fb_cross_20_honest_higher"] += wt
                if c20_l:
                    thr["fb_cross_20_legacy_higher"] += 1
                    thr["wt_fb_cross_20_legacy_higher"] += wt

        design_recs.append({
            "wt": wt,
            "strata": meta.get("strata"),
            "psu": meta.get("psu"),
            "race": race,
            "honest_show": 1.0 if honest_show else 0.0,
            "legacy_show": 1.0 if legacy_show else 0.0,
            "honest_show_40_79": 1.0 if (age_40_79 and honest_show) else 0.0,
            "legacy_show_40_79": 1.0 if (age_40_79 and legacy_show_40) else 0.0,
            "age_40_79": age_40_79,
            "is_white": race == "white",
            "is_aa": race == "aa",
            "misattributed": 1.0 if fallback else 0.0,
            "both_numeric": hp is not None and lp is not None,
            "band_disagree": 1.0 if band_disagree else 0.0,
            "cross_7_5_honest_higher": 1.0 if cross_flags.get("cross_7_5_honest_higher") else 0.0,
            "cross_7_5_legacy_higher": 1.0 if cross_flags.get("cross_7_5_legacy_higher") else 0.0,
        })

    # Design-based CIs (Taylor); jackknife helper retained as documented backup.
    variance_method = _design_meta_method()
    ci_overall_honest = stratified_taylor_rate(design_recs, "honest_show")
    ci_overall_legacy = stratified_taylor_rate(design_recs, "legacy_show")
    # Among ages 40–79: honest_show / apples-to-apples legacy show (no under-40 green).
    ci_h40 = stratified_taylor_rate(design_recs, "honest_show", domain_key="age_40_79")
    ci_l40 = stratified_taylor_rate(design_recs, "legacy_show_40_79", domain_key="age_40_79")
    ci_white_h = stratified_taylor_rate(design_recs, "honest_show", domain_key="is_white")
    ci_aa_h = stratified_taylor_rate(design_recs, "honest_show", domain_key="is_aa")
    ci_mis = stratified_taylor_rate(design_recs, "misattributed")

    design_based_cis = {
        "overall_weighted_honest_show": _ci_block(ci_overall_honest),
        "overall_weighted_legacy_show": _ci_block(ci_overall_legacy),
        "weighted_honest_show_age_40_79": _ci_block(ci_h40),
        "weighted_legacy_show_age_40_79": _ci_block(ci_l40),
        "white_weighted_honest_show": _ci_block(ci_white_h),
        "aa_weighted_honest_show": _ci_block(ci_aa_h),
        "weighted_misattribution_rate_among_all": _ci_block(ci_mis),
        "variance_method": variance_method,
    }

    n_both = max(thr["n_both_numeric"], 1)
    wt_both = max(thr["wt_both"], 1e-9)
    overall_stratum = _stratum_crossing_block(thr, "")
    no_fb_stratum = _stratum_crossing_block(thr, "no_fb_")
    fb_stratum = _stratum_crossing_block(thr, "fb_")
    # Backward-compatible flat keys on white_aa_no_fallback_stratum
    white_aa_compat = {
        **no_fb_stratum,
        "definition": (
            "Both-numeric White or AA persons without legacy_white_fallback "
            "(by construction equals overall no-fallback among both-numeric)."
        ),
        "any_band_disagree_rate": no_fb_stratum["any_band_disagree"]["rate"],
        "crossed_7_5_honest_higher": no_fb_stratum["crossed_7_5"]["honest_higher"],
        "crossed_7_5_legacy_higher": no_fb_stratum["crossed_7_5"]["legacy_higher"],
        "crossed_20_honest_higher": no_fb_stratum["crossed_20"]["honest_higher"],
        "crossed_20_legacy_higher": no_fb_stratum["crossed_20"]["legacy_higher"],
    }
    band_threshold_crossings = {
        "cutpoints_pct": [CUT_5, CUT_7_5, CUT_20],
        "n_both_numeric": thr["n_both_numeric"],
        "any_band_disagree": overall_stratum["any_band_disagree"],
        "crossed_7_5": {
            "honest_higher_risk_than_legacy": {
                **overall_stratum["crossed_7_5"]["honest_higher"],
                "definition": "legacy_pct < 7.5 <= honest_pct (exact percents)",
            },
            "legacy_higher_risk_than_honest": {
                **overall_stratum["crossed_7_5"]["legacy_higher"],
                "definition": "honest_pct < 7.5 <= legacy_pct (exact percents)",
            },
        },
        "crossed_20": {
            "honest_higher_risk_than_legacy": {
                **overall_stratum["crossed_20"]["honest_higher"],
                "definition": "legacy_pct < 20 <= honest_pct (exact percents)",
            },
            "legacy_higher_risk_than_honest": {
                **overall_stratum["crossed_20"]["legacy_higher"],
                "definition": "honest_pct < 20 <= legacy_pct (exact percents)",
            },
        },
        "crossed_5": {
            "honest_higher_risk_than_legacy": {
                "n": thr["cross_5_honest_higher"],
                "rate": round(thr["cross_5_honest_higher"] / n_both, 4),
            },
            "legacy_higher_risk_than_honest": {
                "n": thr["cross_5_legacy_higher"],
                "rate": round(thr["cross_5_legacy_higher"] / n_both, 4),
            },
        },
        "fallback_stratum": {
            **fb_stratum,
            "definition": (
                "Both-numeric persons with legacy_white_fallback true "
                "(misattributed White PCE equation)."
            ),
        },
        "no_fallback_stratum": {
            **no_fb_stratum,
            "definition": (
                "Both-numeric persons without legacy_white_fallback. "
                "Equals white_aa_no_fallback_stratum by legacy construction."
            ),
        },
        "white_aa_no_fallback_stratum": white_aa_compat,
        "note": (
            "Threshold crossings use exact numeric percents when both arms score, "
            "even if band labels would otherwise disagree at non-cut boundaries. "
            "Direction: honest_higher means PREVENT/honest places the person at/above "
            "the cut while legacy PCE is below. "
            "fallback_stratum + no_fallback_stratum partition n_both_numeric."
        ),
    }

    by_race_out = {}
    for race, b in by_race.items():
        n = max(b["n"], 1)
        wt = max(b["wt"], 1e-9)
        if race == "white":
            race_ci = _ci_block(stratified_taylor_rate(design_recs, "honest_show", domain_key="is_white"))
        elif race == "aa":
            race_ci = _ci_block(stratified_taylor_rate(design_recs, "honest_show", domain_key="is_aa"))
        else:
            for r in design_recs:
                r["_race_dom"] = r["race"] == race
            race_ci = _ci_block(stratified_taylor_rate(design_recs, "honest_show", domain_key="_race_dom"))

        by_race_out[race] = {
            "n": b["n"],
            "lab_completeness": {
                "complete_rate": round(b["complete"] / n, 4),
                "egfr_rate": round(b["has_egfr"] / n, 4),
                "lipids_rate": round(b["has_lipids"] / n, 4),
                "sbp_rate": round(b["has_sbp"] / n, 4),
                "bmi_ge_40_rate": round(b["bmi_ge_40"] / n, 4),
            },
            "honest": {
                "show_rate": round(b["honest_show"] / n, 4),
                "refuse_rate": round(b["honest_refuse"] / n, 4),
                "weighted_show_rate": round(b["wt_honest_show"] / wt, 4),
                "weighted_show_ci95": race_ci.get("ci95"),
                "weighted_refuse_rate": round(b["wt_honest_refuse"] / wt, 4),
                "weighted_show_rate_age_40_79": round(
                    b["wt_honest_show_40_79"] / max(b["wt_age_40_79"], 1e-9), 4
                ) if b["n_age_40_79"] else None,
                "refuse_gates": {k: int(v) for k, v in sorted(b["gates"].items())},
                "refuse_gates_weighted_share": {
                    k: round(v / max(b["wt_honest_refuse"], 1e-9), 4)
                    for k, v in sorted(b["gates_wt"].items())
                },
            },
            "legacy": {
                "show_rate": round(b["legacy_show"] / n, 4),
                "weighted_show_rate": round(b["wt_legacy_show"] / wt, 4),
                "weighted_show_rate_age_40_79": round(
                    b["wt_legacy_show_40_79"] / max(b["wt_age_40_79"], 1e-9), 4
                ) if b["n_age_40_79"] else None,
                "white_fallback_rate_among_all": round(b["legacy_fallback"] / n, 4),
                "white_fallback_rate_among_pce_scored": (
                    round(b["legacy_fallback"] / b["legacy_pce_scored"], 4)
                    if b["legacy_pce_scored"] else None
                ),
                "pce_scored_n": b["legacy_pce_scored"],
                "under40_green_rate": round(b["legacy_under40_green"] / n, 4),
                "misattributed_equation_count": b["legacy_fallback"],
            },
            "reclassification_when_both_numeric": {
                "n": b["reclass_n"],
                "band_disagree_rate": round(b["reclass_diff_band"] / max(b["reclass_n"], 1), 4),
                "mean_abs_delta_pp": round(b["abs_delta_sum"] / max(b["reclass_n"], 1), 4),
                "no_fallback_stratum_n": b["reclass_no_fallback_n"],
                "no_fallback_band_disagree_rate": round(
                    b["reclass_no_fallback_diff"] / max(b["reclass_no_fallback_n"], 1), 4
                ) if b["reclass_no_fallback_n"] else None,
            },
            "note": (
                "RIDRETH3=6 Non-Hispanic Asian (South+East combined). "
                "Fallback among PCE-scored non-White/non-AA is 1.0 by legacy construction."
                if race == "asian_nhanes"
                else (
                    "Fallback among PCE-scored non-White/non-AA is 1.0 by construction."
                    if race in ("hispanic", "multiracial") else None
                )
            ),
        }

    mis_count = overall["legacy_fallback"]  # fixed construction count (1967 by design on full run)
    wt_mis_rate = round(
        sum(r["wt"] * r["misattributed"] for r in design_recs) / max(overall["wt"], 1e-9), 4
    )

    summary = {
        "source": "NHANES 2017-March 2020 pre-pandemic public XPT",
        "files": ["P_DEMO", "P_BPXO", "P_BMX", "P_HDL", "P_TCHOL", "P_BIOPRO", "P_SMQ", "P_DIQ", "P_BPQ"],
        "egfr_equation": "CKD-EPI 2021 creatinine race-free",
        "seed": SEED,
        "max_n": MAX_N,
        "n_full_eligible": full_n,
        "n_analyzed": overall["n"],
        "overall": {
            "honest_show_rate": round(overall["honest_show"] / max(overall["n"], 1), 4),
            "weighted_honest_show_rate": round(overall["wt_honest_show"] / max(overall["wt"], 1e-9), 4),
            "legacy_show_rate": round(overall["legacy_show"] / max(overall["n"], 1), 4),
            "weighted_legacy_show_rate": round(overall["wt_legacy_show"] / max(overall["wt"], 1e-9), 4),
            "band_reclass_no_fallback_white_aa": round(
                overall["reclass_no_fallback_diff"] / max(overall["reclass_no_fallback_n"], 1), 4
            ) if overall["reclass_no_fallback_n"] else None,
            "legacy_white_fallback_rate_among_all": round(overall["legacy_fallback"] / max(overall["n"], 1), 4),
            "legacy_pce_scored_n": overall["legacy_pce_scored"],
            "legacy_white_fallback_rate_among_pce_scored": (
                round(overall["legacy_fallback"] / overall["legacy_pce_scored"], 4)
                if overall["legacy_pce_scored"] else None
            ),
            "misattributed_equation_count": mis_count,
            "weighted_misattribution_rate_among_all": wt_mis_rate,
            "unweighted_misattribution_rate_among_all": round(mis_count / max(overall["n"], 1), 4),
            "band_reclassification_rate_when_both_numeric": round(
                overall["reclass_diff_band"] / max(overall["reclass_n"], 1), 4
            ),
            "weighted_honest_show_rate_age_40_79": round(
                overall["wt_honest_show_40_79"] / max(overall["wt_age_40_79"], 1e-9), 4
            ) if overall["n_age_40_79"] else None,
            "weighted_legacy_show_rate_age_40_79": round(
                overall["wt_legacy_show_40_79"] / max(overall["wt_age_40_79"], 1e-9), 4
            ) if overall["n_age_40_79"] else None,
            "design_based_cis": design_based_cis,
            "band_threshold_crossings": band_threshold_crossings,
            "construction_note": (
                "For races outside {white,aa}, every legacy PCE score is a White fallback by design. "
                "NHANES estimates burden counts, weighted show/refuse, gate decomposition, and band shifts. "
                "Primary apples-to-apples coverage contrast uses ages 40–79 (excludes legacy under-40 green). "
                "Misattribution point count is unweighted headcount among analyzed adults (1967/7172 on full run); "
                "weighted rate + design-based CI are reported separately and do not alter the count."
            ),
        },
        "by_race": by_race_out,
        "audit_design": {
            "daily_lifestyle": "empty — CVD path only; no fabricated complete diary",
            "age_primary_contrast": "40-79",
            "variance": variance_method,
        },
        "limitations": [
            "Full eligible adults 30–79 with exam weight WTMECPRP (pre-pandemic 2017–March 2020).",
            "Cross-sectional; no mortality linkage / clinical calibration.",
            "Design-based SEs use stratified Taylor linearization (with-replacement PSUs within SDMVSTRA); singleton strata skipped.",
            "RIDRETH3=6 combines South+East Asian; DIQ/BPQ residual misclassification possible.",
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _sync_tables(summary)

    print(json.dumps({
        "n": summary["n_analyzed"],
        "full_eligible": full_n,
        "misattributed_equation_count": mis_count,
        "design_based_cis": {
            k: v for k, v in design_based_cis.items() if k != "variance_method"
        },
        "band_threshold_crossings": {
            "any_band_disagree": band_threshold_crossings["any_band_disagree"],
            "crossed_7_5": band_threshold_crossings["crossed_7_5"],
            "crossed_20": band_threshold_crossings["crossed_20"],
            "fallback_stratum": band_threshold_crossings["fallback_stratum"],
            "no_fallback_stratum": band_threshold_crossings["no_fallback_stratum"],
            "white_aa_no_fallback": band_threshold_crossings["white_aa_no_fallback_stratum"],
        },
        "wrote": str(OUT),
        "tables_synced": str(TABLES),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
