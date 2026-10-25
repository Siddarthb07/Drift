#!/usr/bin/env python3
"""
NHANES 2017–March 2020 disclosure-disparity + risk-reclassification audit.

- eGFR: 2021 race-free CKD-EPI creatinine
- Survey weights (WTMECPRP) for weighted rates
- Refusal gate decomposition by race
- Legacy vs honest band reclassification / misattribution burden

Honest about construction: among PCE-scored non-White/non-AA, White fallback = 1.0 by legacy design.
"""
from __future__ import annotations

import json
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


def main():
    rng = np.random.default_rng(SEED)
    df = build_frame()
    full_n = len(df)
    if MAX_N is not None and len(df) > MAX_N:
        idx = rng.choice(len(df), size=MAX_N, replace=False)
        df = df.iloc[idx].copy()

    daily = [{
        "sleep": 7, "steps": 8000, "stress_level": 4, "active_minutes": 25,
        "veg_servings": 2, "fruit_servings": 1, "red_meat_servings": 1, "processed_meat": 0,
    }] * 14

    by_race = defaultdict(lambda: {
        "n": 0, "wt": 0.0, "complete": 0, "has_egfr": 0, "has_lipids": 0, "has_sbp": 0,
        "honest_show": 0, "honest_refuse": 0, "wt_honest_show": 0.0, "wt_honest_refuse": 0.0,
        "legacy_fallback": 0, "legacy_pce_scored": 0, "legacy_under40_green": 0,
        "gates": defaultdict(float), "gates_wt": defaultdict(float),
        "reclass_diff_band": 0, "reclass_n": 0, "abs_delta_sum": 0.0,
        "bmi_ge_40": 0,
    })
    overall = {
        "n": 0, "wt": 0.0, "honest_show": 0, "legacy_fallback": 0, "legacy_pce_scored": 0,
        "wt_honest_show": 0.0, "reclass_diff_band": 0, "reclass_n": 0,
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

        if _honest_shows(hc):
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
        if lc.get("legacy_white_fallback"):
            b["legacy_fallback"] += 1
            overall["legacy_fallback"] += 1
        if "Under 40" in str(lc.get("risk_category") or ""):
            b["legacy_under40_green"] += 1

        # Reclassification when both produce a numeric (honest exact vs legacy pct)
        hp = _exact_pct(hc)
        lp = _exact_pct(lc)
        if hp is not None and lp is not None:
            b["reclass_n"] += 1
            overall["reclass_n"] += 1
            b["abs_delta_sum"] += abs(hp - lp)
            if _band(hp) != _band(lp):
                b["reclass_diff_band"] += 1
                overall["reclass_diff_band"] += 1

    by_race_out = {}
    for race, b in by_race.items():
        n = max(b["n"], 1)
        wt = max(b["wt"], 1e-9)
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
                "weighted_refuse_rate": round(b["wt_honest_refuse"] / wt, 4),
                "refuse_gates": {k: int(v) for k, v in sorted(b["gates"].items())},
                "refuse_gates_weighted_share": {
                    k: round(v / max(b["wt_honest_refuse"], 1e-9), 4)
                    for k, v in sorted(b["gates_wt"].items())
                },
            },
            "legacy": {
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
            "legacy_white_fallback_rate_among_all": round(overall["legacy_fallback"] / max(overall["n"], 1), 4),
            "legacy_pce_scored_n": overall["legacy_pce_scored"],
            "legacy_white_fallback_rate_among_pce_scored": (
                round(overall["legacy_fallback"] / overall["legacy_pce_scored"], 4)
                if overall["legacy_pce_scored"] else None
            ),
            "misattributed_equation_count": overall["legacy_fallback"],
            "band_reclassification_rate_when_both_numeric": round(
                overall["reclass_diff_band"] / max(overall["reclass_n"], 1), 4
            ),
            "construction_note": (
                "For races outside {white,aa}, every legacy PCE score is a White fallback by design. "
                "NHANES estimates burden counts, weighted show/refuse, gate decomposition, and band shifts."
            ),
        },
        "by_race": by_race_out,
        "limitations": [
            "Full eligible adults 30–79 with exam weight WTMECPRP (pre-pandemic 2017–March 2020).",
            "Cross-sectional; no mortality linkage / clinical calibration; no survey-design (strata/PSU) variance here.",
            "RIDRETH3=6 combines South+East Asian; DIQ/BPQ residual misclassification possible.",
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({
        "n": summary["n_analyzed"],
        "full_eligible": full_n,
        "overall": summary["overall"],
        "by_race": {
            k: {
                "n": v["n"],
                "honest_show": v["honest"]["show_rate"],
                "weighted_show": v["honest"]["weighted_show_rate"],
                "misattributed_n": v["legacy"]["misattributed_equation_count"],
                "gates": v["honest"]["refuse_gates"],
                "band_reclass": v["reclassification_when_both_numeric"]["band_disagree_rate"],
            }
            for k, v in by_race_out.items()
        },
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
