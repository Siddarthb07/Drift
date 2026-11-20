#!/usr/bin/env python3
"""A4: Model-choice uncertainty on NHANES — band disagreement across guideline-valid equations.

Equations (White/AA ages 40–79 for PCE-family; PREVENT when in range):
  - PCE Goff 2013
  - Yadlowsky 2018 revised PCE (logistic Model Set 2; PooledCohort coeffs)
  - PREVENT base ASCVD Khan 2024

Reports raw band disagreement and disagreement after removing the mean PCE−PREVENT
shift (so systematic recalibration is not mistaken for residual imprecision).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from prevent_equations import prevent_10yr
from risk_calculators import pooled_cohort_cvd_10yr

NHANES = ROOT / "data" / "nhanes"
OUT = ROOT / "docs" / "jbhi" / "outside_corpus" / "false_precision_report.json"
PAIR = ROOT / "docs" / "jbhi" / "outside_corpus" / "nhanes_equation_pair_exact.json"

RACE_MAP = {1: "hispanic", 2: "hispanic", 3: "white", 4: "aa", 6: "asian_nhanes", 7: "multiracial"}

# Yadlowsky 2018 Model Set 2 (sex-specific logistic); source: bcjaeger/PooledCohort
# (matches Ann Intern Med supplement examples to 0.1 pp).
_YAD = {
    "female": dict(
        intercept=-12.823110, age=0.106501, black=0.432440, sbp2=0.000056, sbp=0.017666,
        bp_meds=0.731678, diabetes=0.943970, smoke=1.009790, chol_r=0.151318, age_black=-0.008580,
        sbp_bpmed=-0.003647, sbp_black=0.006208, bpmed_black=0.152968, age_sbp=-0.000153,
        black_dm=0.115232, black_sm=-0.092231, black_chol=0.070498, black_sbp_bpmed=-0.000173,
        black_sbp_age=-0.000094,
    ),
    "male": dict(
        intercept=-11.679980, age=0.064200, black=0.482835, sbp2=-0.000061, sbp=0.038950,
        bp_meds=2.055533, diabetes=0.842209, smoke=0.895589, chol_r=0.193307, age_black=0.0,
        sbp_bpmed=-0.014207, sbp_black=0.011609, bpmed_black=-0.119460, age_sbp=0.000025,
        black_dm=-0.077214, black_sm=-0.226771, black_chol=-0.117749, black_sbp_bpmed=0.004190,
        black_sbp_age=-0.000199,
    ),
}


def band(pct: float) -> str:
    if pct < 5:
        return "<5"
    if pct < 7.5:
        return "5-7.5"
    if pct < 20:
        return "7.5-20"
    return ">=20"


def yadlowsky_pct(
    sex: str, age: float, race: str, tc: float, hdl: float, sbp: float,
    bp_tx: bool, smoker: bool, diabetes: bool,
) -> Optional[float]:
    if sex not in _YAD or race not in ("white", "aa") or not (40 <= age <= 79):
        return None
    if hdl <= 0:
        return None
    C = _YAD[sex]
    b = 1.0 if race == "aa" else 0.0
    bp = 1.0 if bp_tx else 0.0
    sm = 1.0 if smoker else 0.0
    dm = 1.0 if diabetes else 0.0
    cr = tc / hdl
    s = (
        C["intercept"] + C["age"] * age + C["black"] * b + C["sbp2"] * (sbp ** 2)
        + C["sbp"] * sbp + C["bp_meds"] * bp + C["diabetes"] * dm + C["smoke"] * sm
        + C["chol_r"] * cr + C["age_black"] * age * b + C["sbp_bpmed"] * sbp * bp
        + C["sbp_black"] * sbp * b + C["bpmed_black"] * bp * b + C["age_sbp"] * age * sbp
        + C["black_dm"] * b * dm + C["black_sm"] * b * sm + C["black_chol"] * b * cr
        + C["black_sbp_bpmed"] * b * sbp * bp + C["black_sbp_age"] * b * sbp * age
    )
    return 100.0 / (1.0 + math.exp(-s))


def ckdepi2021(scr: float, age: float, female: bool) -> float:
    kappa = 0.7 if female else 0.9
    alpha = -0.241 if female else -0.302
    scr_k = scr / kappa
    return float(
        142 * (min(scr_k, 1) ** alpha) * (max(scr_k, 1) ** -1.200)
        * (0.9938 ** age) * (1.012 if female else 1.0)
    )


def _read(name: str) -> pd.DataFrame:
    return pd.read_sas(NHANES / f"{name}.xpt", format="xport")


def load_adults() -> pd.DataFrame:
    demo = _read("P_DEMO")
    bpx = _read("P_BPXO")
    bmx = _read("P_BMX")
    hdl = _read("P_HDL")
    tc = _read("P_TCHOL")
    bio = _read("P_BIOPRO")
    smq = _read("P_SMQ") if (NHANES / "P_SMQ.xpt").exists() else None
    diq = _read("P_DIQ") if (NHANES / "P_DIQ.xpt").exists() else None
    bpq = _read("P_BPQ") if (NHANES / "P_BPQ.xpt").exists() else None

    df = demo.merge(bpx, on="SEQN", how="left")
    df = df.merge(bmx, on="SEQN", how="left")
    df = df.merge(hdl, on="SEQN", how="left")
    df = df.merge(tc, on="SEQN", how="left")
    df = df.merge(bio, on="SEQN", how="left")
    if smq is not None:
        df = df.merge(smq, on="SEQN", how="left")
    if diq is not None:
        df = df.merge(diq, on="SEQN", how="left")
    if bpq is not None:
        df = df.merge(bpq, on="SEQN", how="left")

    df = df[df["WTMECPRP"] > 0].copy()
    df["age"] = df["RIDAGEYR"]
    df = df[(df["age"] >= 30) & (df["age"] <= 79)].copy()
    df["sex"] = df["RIAGENDR"].map({1: "male", 2: "female"})
    df["race"] = df["RIDRETH3"].map(RACE_MAP)
    sbp_cols = [c for c in df.columns if c.startswith("BPXOS") and c.endswith("S")]
    if not sbp_cols:
        sbp_cols = [c for c in ("BPXOSY1", "BPXOSY2", "BPXOSY3") if c in df.columns]
    df["sbp"] = df[sbp_cols].mean(axis=1, skipna=True) if sbp_cols else np.nan
    df["tc"] = df.get("LBXTC")
    df["hdl"] = df.get("LBDHDD")
    df["bmi"] = df.get("BMXBMI")
    scr = df.get("LBXSCR")
    female = df["sex"] == "female"
    df["egfr"] = [
        ckdepi2021(float(s), float(a), bool(f)) if pd.notna(s) and pd.notna(a) else np.nan
        for s, a, f in zip(scr, df["age"], female)
    ]
    df["smoker"] = df["SMQ040"].isin([1, 2]) if "SMQ040" in df.columns else False
    df["diabetes"] = df["DIQ010"] == 1 if "DIQ010" in df.columns else False
    if "BPQ050A" in df.columns:
        df["bp_tx"] = df["BPQ050A"] == 1
    elif "BPQ040A" in df.columns:
        df["bp_tx"] = df["BPQ040A"] == 1
    else:
        df["bp_tx"] = False
    return df


def _pce_pct(pce: Any) -> Optional[float]:
    if not isinstance(pce, dict):
        return None
    # risk_pct / ten_year_risk_pct are already percentage points (e.g. 1.4 = 1.4%).
    for k in ("risk_pct", "ten_year_risk_pct"):
        if k in pce and isinstance(pce[k], (int, float)):
            v = float(pce[k])
            return v if 0.0 <= v <= 100.0 else None
    for k in ("risk", "ascvd", "percent"):
        if k in pce and isinstance(pce[k], (int, float)):
            v = float(pce[k])
            # Fractions in (0,1] → percent; already-percent values left as-is.
            if 0.0 < v <= 1.0:
                v *= 100.0
            return v if 0.0 <= v <= 100.0 else None
    return None


def score_row(r: pd.Series) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "seqn": int(r["SEQN"]),
        "weight": float(r["WTMECPRP"]),
        "race": r.get("race"),
    }
    sex = r["sex"]
    age = float(r["age"])
    race = r.get("race")
    tc, hdl, sbp = r.get("tc"), r.get("hdl"), r.get("sbp")
    if any(pd.isna(x) for x in (tc, hdl, sbp, sex)):
        return out
    bp_tx, smoker, diabetes = bool(r.get("bp_tx")), bool(r.get("smoker")), bool(r.get("diabetes"))

    if race in ("white", "aa") and 40 <= age <= 79:
        pce = pooled_cohort_cvd_10yr(
            age, sex, float(tc), float(hdl), float(sbp), bp_tx, smoker, diabetes, race,
        )
        pct = _pce_pct(pce)
        if pct is not None:
            out["pce_pct"] = pct
        y = yadlowsky_pct(sex, age, race, float(tc), float(hdl), float(sbp), bp_tx, smoker, diabetes)
        if y is not None:
            out["yadlowsky_pct"] = y

    egfr, bmi = r.get("egfr"), r.get("bmi")
    if pd.notna(egfr) and pd.notna(bmi) and 30 <= age <= 79:
        prev = prevent_10yr(
            sex=sex, age=age, total_chol=float(tc), hdl_chol=float(hdl), sbp=float(sbp),
            diabetes=diabetes, current_smoker=smoker, bmi=float(bmi), egfr=float(egfr),
            bp_treated=bp_tx, outcome="ascvd",
        )
        if isinstance(prev, dict):
            if "risk_pct" in prev:
                out["prevent_pct"] = float(prev["risk_pct"])
            else:
                for k, v in prev.items():
                    if "risk" in k and isinstance(v, (int, float)):
                        vv = float(v)
                        out["prevent_pct"] = vv * 100 if vv <= 1.5 else vv
                        break
    return out


def design_based_share(rows: List[Dict], key_flag: str) -> Dict[str, Any]:
    w_num = w_den = 0.0
    k = n = 0
    for r in rows:
        w = float(r["weight"])
        w_den += w
        n += 1
        if r.get(key_flag):
            w_num += w
            k += 1
    rate = w_num / w_den if w_den else 0.0
    z = 1.96
    p = k / n if n else 0.0
    den = 1 + z * z / n if n else 1
    center = (p + z * z / (2 * n)) / den if n else 0
    half = (z / den) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) if n else 0
    return {
        "weighted_share": rate,
        "unweighted_share": p,
        "unweighted_wilson95": [max(0, center - half), min(1, center + half)],
        "n": n,
        "k": k,
    }


def weighted_mean_diff(rows: List[Dict], a: str, b: str) -> Optional[float]:
    num = den = 0.0
    for r in rows:
        if r.get(a) is None or r.get(b) is None:
            continue
        w = float(r["weight"])
        num += w * (float(r[a]) - float(r[b]))
        den += w
    return (num / den) if den else None


def weighted_mean_log_ratio(rows: List[Dict], a: str, b: str) -> Optional[float]:
    """Weighted mean of log(a/b); used for proportional (multiplicative) recalibration."""
    num = den = 0.0
    for r in rows:
        av, bv = r.get(a), r.get(b)
        if av is None or bv is None:
            continue
        av, bv = float(av), float(bv)
        if av <= 0 or bv <= 0:
            continue
        w = float(r["weight"])
        num += w * math.log(av / bv)
        den += w
    return (num / den) if den else None


def _rank_band(pct: float, sorted_vals: np.ndarray) -> str:
    """Map a percent to empirical quartile labels of a reference distribution."""
    if len(sorted_vals) == 0:
        return "na"
    # percentile rank in [0,100]
    rank = float(np.searchsorted(sorted_vals, pct, side="right")) / len(sorted_vals) * 100.0
    if rank < 25:
        return "Q1"
    if rank < 50:
        return "Q2"
    if rank < 75:
        return "Q3"
    return "Q4"


def main() -> int:
    df = load_adults()
    rows = [score_row(r) for _, r in df.iterrows()]

    # Primary pair: Goff PCE vs PREVENT (White/AA only by construction of PCE)
    pair = [r for r in rows if r.get("pce_pct") is not None and r.get("prevent_pct") is not None]
    mean_shift = weighted_mean_diff(pair, "pce_pct", "prevent_pct")  # PCE − PREVENT
    mean_log_ratio = weighted_mean_log_ratio(pair, "pce_pct", "prevent_pct")  # E[log(PCE/PREVENT)]
    ratio_factor = math.exp(mean_log_ratio) if mean_log_ratio is not None else None

    # Empiricial distributions for rank-based comparison (unweighted for rank stability)
    pce_sorted = np.sort(np.array([float(r["pce_pct"]) for r in pair]))
    prev_sorted = np.sort(np.array([float(r["prevent_pct"]) for r in pair]))

    analyzed = []
    spreads = []
    shift_spreads = []
    for r in pair:
        pce, prev = float(r["pce_pct"]), float(r["prevent_pct"])
        vals = [pce, prev]
        if r.get("yadlowsky_pct") is not None:
            vals.append(float(r["yadlowsky_pct"]))
        bands = {band(v) for v in vals}
        r2 = dict(r)
        r2["band_disagree_raw"] = band(pce) != band(prev)
        r2["band_disagree_any_eq"] = len(bands) > 1
        r2["pp_spread"] = abs(pce - prev)
        # Additive mean-shift removal
        pce_add = pce - (mean_shift or 0.0)
        r2["band_disagree_shift_adj"] = band(pce_add) != band(prev)
        r2["pp_spread_shift_adj"] = abs(pce_add - prev)
        # Proportional (log-ratio) recalibration: PCE / exp(E[log(PCE/PREVENT)])
        if ratio_factor and ratio_factor > 0:
            pce_prop = pce / ratio_factor
        else:
            pce_prop = pce
        r2["band_disagree_proportional"] = band(pce_prop) != band(prev)
        # Rank-based: empirical quartile of each equation within its own distribution
        r2["band_disagree_rank_quartile"] = _rank_band(pce, pce_sorted) != _rank_band(prev, prev_sorted)
        spreads.append(r2["pp_spread"])
        shift_spreads.append(r2["pp_spread_shift_adj"])
        analyzed.append(r2)

    # Triple when Yadlowsky present
    triple = [r for r in analyzed if r.get("yadlowsky_pct") is not None]
    for r in triple:
        vals = [float(r["pce_pct"]), float(r["yadlowsky_pct"]), float(r["prevent_pct"])]
        r["band_disagree_triple"] = len({band(v) for v in vals}) > 1
        # pairwise Goff vs Yadlowsky
        r["band_disagree_pce_yad"] = band(float(r["pce_pct"])) != band(float(r["yadlowsky_pct"]))

    stats_raw = design_based_share(analyzed, "band_disagree_raw")
    stats_adj = design_based_share(analyzed, "band_disagree_shift_adj")
    stats_prop = design_based_share(analyzed, "band_disagree_proportional")
    stats_rank = design_based_share(analyzed, "band_disagree_rank_quartile")
    stats_any = design_based_share(analyzed, "band_disagree_any_eq") if analyzed else {}
    stats_triple = design_based_share(triple, "band_disagree_triple") if triple else {}
    stats_pce_yad = design_based_share(triple, "band_disagree_pce_yad") if triple else {}

    for thr, name in [(1.0, "spread_ge_1pp"), (2.0, "spread_ge_2pp"), (5.0, "spread_ge_5pp")]:
        for r in analyzed:
            r[name] = r["pp_spread"] >= thr
    spread_stats = {
        name: design_based_share(analyzed, name)
        for name in ("spread_ge_1pp", "spread_ge_2pp", "spread_ge_5pp")
    }

    sentence = (
        f"Among White/AA adults with both Goff PCE and PREVENT numerics (n={stats_raw['n']}), "
        f"survey-weighted model-choice band disagreement is {stats_raw['weighted_share']:.1%} raw, "
        f"{stats_adj['weighted_share']:.1%} after additive mean-shift removal, "
        f"{stats_prop['weighted_share']:.1%} after proportional (log-ratio) recalibration, "
        f"and {stats_rank['weighted_share']:.1%} on empirical quartile ranks. "
        f"Frame: residual model-choice uncertainty among guideline-valid equations."
    )

    report = {
        "equations": [
            "pce_goff2013",
            "yadlowsky2018_revised_pce",
            "prevent_base_ascvd_khan2024",
        ],
        "population_note": "PCE-family scores only White/AA ages 40–79; n with both PCE and PREVENT is that stratum.",
        "yadlowsky2018": {
            "status": "scored",
            "source": "PooledCohort::_pcr_Yadlowsky_2013 logistic Model Set 2 coeffs",
            "example_55yo_check": {"bf": 1.8, "wf": 1.2, "bm": 3.5, "wm": 3.3},
        },
        "n_adults_loaded": int(len(df)),
        "n_with_pce_and_prevent": stats_raw["n"],
        "n_with_ge2_equations": stats_raw["n"],  # backward-compatible key
        "mean_pce_minus_prevent_pp": mean_shift,
        "mean_log_pce_over_prevent": mean_log_ratio,
        "proportional_ratio_factor": ratio_factor,
        "band_disagreement": stats_raw,  # raw Goff vs PREVENT (compat)
        "band_disagreement_raw_pce_prevent": stats_raw,
        "band_disagreement_shift_adjusted": stats_adj,
        "band_disagreement_proportional": stats_prop,
        "band_disagreement_rank_quartile": stats_rank,
        "band_disagreement_any_including_yadlowsky": stats_any,
        "band_disagreement_triple": stats_triple,
        "band_disagreement_pce_vs_yadlowsky": stats_pce_yad,
        "mean_pp_spread": float(np.mean(spreads)) if spreads else None,
        "median_pp_spread": float(np.median(spreads)) if spreads else None,
        "mean_pp_spread_shift_adj": float(np.mean(shift_spreads)) if shift_spreads else None,
        "spread_thresholds": spread_stats,
        "sentence": sentence,
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    PAIR.write_text(json.dumps({
        "n": len(analyzed),
        "mean_shift_pp": mean_shift,
        "proportional_ratio_factor": ratio_factor,
        "rows_sample": analyzed[:40],
        "note": "Aggregates in false_precision_report.json; White/AA stratum only.",
    }, indent=2) + "\n")
    print(json.dumps({
        "n": stats_raw["n"],
        "raw": round(stats_raw["weighted_share"], 4),
        "additive": round(stats_adj["weighted_share"], 4),
        "proportional": round(stats_prop["weighted_share"], 4),
        "rank_q": round(stats_rank["weighted_share"], 4),
        "mean_shift": round(mean_shift or 0, 3),
        "ratio_factor": round(ratio_factor or 0, 3),
        "triple": round(stats_triple.get("weighted_share", 0), 4) if stats_triple else None,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
