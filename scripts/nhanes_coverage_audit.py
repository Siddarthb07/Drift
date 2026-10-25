#!/usr/bin/env python3
"""
NHANES 2017–March 2020 disclosure-disparity audit.

Measures, by race/ethnicity stratum:
  - lab completeness (SBP, lipids, eGFR proxy via creatinine)
  - honest engine: show vs refuse rates under observed missingness
  - legacy baseline: White-PCE fallback rate when CVD is scored

Uses public CDC XPT files under data/nhanes/. Not outcome-linked;
coverage/fallback only — no calibration claim.
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
MAX_N = 2500  # subsample for runtime; seed-pinned

# RIDRETH3 codes (NHANES)
RACE_MAP = {
    1: "hispanic",  # Mexican American
    2: "hispanic",  # Other Hispanic
    3: "white",
    4: "aa",
    6: "asian_nhanes",  # RIDRETH3=6 Non-Hispanic Asian (South+East combined)
    7: "multiracial",  # Other / Multi
}


def _read(name: str):
    path = NHANES / f"{name}.xpt"
    if not path.exists() or path.stat().st_size < 50_000:
        raise FileNotFoundError(f"Missing or truncated {path}")
    # pandas.read_sas handles CDC XPORT without pyreadstat
    return pd.read_sas(path, format="xport")


def _egfr_ckd_epi_approx(scr_mgdl: float, age: float, female: bool, black: bool) -> float:
    """2009 CKD-EPI approx for coverage only (not Drift product path)."""
    if scr_mgdl is None or np.isnan(scr_mgdl) or scr_mgdl <= 0:
        return float("nan")
    kappa = 0.7 if female else 0.9
    alpha = -0.329 if female else -0.411
    scr_k = scr_mgdl / kappa
    min_sk = min(scr_k, 1.0) ** alpha
    max_sk = max(scr_k, 1.0) ** -1.209
    egfr = 141 * min_sk * max_sk * (0.993 ** age)
    if female:
        egfr *= 1.018
    if black:
        egfr *= 1.159
    return float(egfr)


def build_frame():
    demo = _read("P_DEMO")
    bpx = _read("P_BPXO")
    bmx = _read("P_BMX")
    hdl = _read("P_HDL")
    tchol = _read("P_TCHOL")
    bio = _read("P_BIOPRO")
    smq = _read("P_SMQ") if (NHANES / "P_SMQ.xpt").exists() else None
    diq = _read("P_DIQ") if (NHANES / "P_DIQ.xpt").exists() and (NHANES / "P_DIQ.xpt").stat().st_size > 50_000 else None
    bpq = _read("P_BPQ") if (NHANES / "P_BPQ.xpt").exists() and (NHANES / "P_BPQ.xpt").stat().st_size > 50_000 else None

    df = demo.merge(bpx, on="SEQN", how="left")
    df = df.merge(bmx, on="SEQN", how="left")
    df = df.merge(hdl, on="SEQN", how="left")
    df = df.merge(tchol, on="SEQN", how="left")
    df = df.merge(bio, on="SEQN", how="left")
    if smq is not None:
        df = df.merge(smq, on="SEQN", how="left")
    if diq is not None:
        df = df.merge(diq, on="SEQN", how="left")
    if bpq is not None:
        df = df.merge(bpq, on="SEQN", how="left")

    # Adults 30–79 (PREVENT age band)
    df = df[(df["RIDAGEYR"] >= 30) & (df["RIDAGEYR"] <= 79)].copy()
    df = df[df["RIAGENDR"].isin([1, 2])]
    df = df[df["RIDRETH3"].isin(RACE_MAP.keys())]
    return df


def row_to_user(row):
    age = float(row["RIDAGEYR"])
    female = int(row["RIAGENDR"]) == 2
    sex = "female" if female else "male"
    race = RACE_MAP[int(row["RIDRETH3"])]
    black = race == "aa"
    height = float(row["BMXHT"]) if row.get("BMXHT") == row.get("BMXHT") else None
    weight = float(row["BMXWT"]) if row.get("BMXWT") == row.get("BMXWT") else None
    # Oscillometric SBP: mean of available readings
    sbps = [row.get(c) for c in ("BPXOSY1", "BPXOSY2", "BPXOSY3") if c in row.index]
    sbps = [float(x) for x in sbps if x == x and x is not None]
    sbp = float(np.mean(sbps)) if sbps else None
    tc = float(row["LBXTC"]) if row.get("LBXTC") == row.get("LBXTC") else None
    hdlv = float(row["LBDHDD"]) if row.get("LBDHDD") == row.get("LBDHDD") else None
    scr = float(row["LBXSCR"]) if row.get("LBXSCR") == row.get("LBXSCR") else None
    egfr = _egfr_ckd_epi_approx(scr, age, female, black) if scr else float("nan")
    smoker = False
    if "SMQ040" in row.index and row.get("SMQ040") == row.get("SMQ040"):
        try:
            smoker = int(row["SMQ040"]) in (1, 2)  # every day / some days
        except (TypeError, ValueError):
            smoker = False
    diabetes = False
    if "DIQ010" in row.index and row.get("DIQ010") == row.get("DIQ010"):
        try:
            diabetes = int(row["DIQ010"]) == 1  # Yes
        except (TypeError, ValueError):
            diabetes = False
    bp_meds = False
    if "BPQ050A" in row.index and row.get("BPQ050A") == row.get("BPQ050A"):
        try:
            bp_meds = int(row["BPQ050A"]) == 1  # now taking prescribed meds for HBP
        except (TypeError, ValueError):
            bp_meds = False

    user = {
        "age": age,
        "sex": sex,
        "sex_for_equation": sex,
        "height": height or 170,
        "weight": weight or 70,
        "waist_cm": float(row["BMXWAIST"]) if row.get("BMXWAIST") == row.get("BMXWAIST") else None,
        "systolic": sbp,
        "race": race,
        "smoking_status": "current" if smoker else "never",
        "bp_medication": int(bp_meds),
        "existing_diabetes": int(diabetes),
        "high_glucose_history": 0,
        "family_history_diabetes": 0,
        "family_history_cancer": 0,
        "alcohol_per_week": 0,
        "region": "global",
    }
    labs = {}
    if tc is not None:
        labs["total_cholesterol"] = tc
    if hdlv is not None:
        labs["hdl_cholesterol"] = hdlv
    if egfr == egfr:
        labs["egfr"] = egfr
    return user, labs, {
        "has_sbp": sbp is not None,
        "has_lipids": tc is not None and hdlv is not None,
        "has_egfr": egfr == egfr,
        "complete": sbp is not None and tc is not None and hdlv is not None and egfr == egfr,
        "race": race,
        "wt": float(row["WTMEC4YR"]) if "WTMEC4YR" in row.index and row.get("WTMEC4YR") == row.get("WTMEC4YR") else 1.0,
    }


def main():
    rng = np.random.default_rng(SEED)
    df = build_frame()
    if len(df) > MAX_N:
        idx = rng.choice(len(df), size=MAX_N, replace=False)
        df = df.iloc[idx].copy()

    daily = [{
        "sleep": 7, "steps": 8000, "stress_level": 4, "active_minutes": 25,
        "veg_servings": 2, "fruit_servings": 1, "red_meat_servings": 1, "processed_meat": 0,
    }] * 14

    by_race = defaultdict(lambda: {
        "n": 0, "complete": 0, "has_egfr": 0, "has_lipids": 0, "has_sbp": 0,
        "honest_show": 0, "honest_refuse": 0,
        "legacy_show": 0, "legacy_fallback": 0, "legacy_under40_green": 0,
        "legacy_pce_scored": 0,
        "wt_complete": 0.0, "wt_n": 0.0,
    })
    overall = {"n": 0, "honest_show": 0, "legacy_fallback": 0, "legacy_pce_scored": 0}

    for _, row in df.iterrows():
        try:
            user, labs, meta = row_to_user(row)
        except Exception:
            continue
        race = meta["race"]
        bucket = by_race[race]
        bucket["n"] += 1
        bucket["wt_n"] += meta["wt"]
        overall["n"] += 1
        for k in ("complete", "has_egfr", "has_lipids", "has_sbp"):
            if meta[k]:
                bucket[k] += 1
        if meta["complete"]:
            bucket["wt_complete"] += meta["wt"]

        honest = compute_risk_scores(user, daily, labs, mode="honest", username="nhanes")
        legacy = compute_risk_scores(user, daily, labs, mode="baseline", username="nhanes")
        hc = honest.get("CVD") or {}
        lc = legacy.get("CVD") or {}

        honest_shows = (
            not hc.get("refused")
            and (
                hc.get("risk_pct") is not None
                or hc.get("risk_band_label")
                or hc.get("risk_pct_exact") is not None
            )
        )
        if honest_shows:
            bucket["honest_show"] += 1
            overall["honest_show"] += 1
        else:
            bucket["honest_refuse"] += 1

        # PCE scored = numeric risk_pct present (not under-40 green, not chol refuse)
        pce_scored = lc.get("risk_pct") is not None
        if pce_scored:
            bucket["legacy_pce_scored"] += 1
            overall["legacy_pce_scored"] += 1
        if lc.get("legacy_white_fallback"):
            bucket["legacy_fallback"] += 1
            overall["legacy_fallback"] += 1
        if pce_scored or "Under 40" in str(lc.get("risk_category") or ""):
            bucket["legacy_show"] += 1
        if "Under 40" in str(lc.get("risk_category") or ""):
            bucket["legacy_under40_green"] += 1

    by_race_out = {}
    for race, b in by_race.items():
        n = max(b["n"], 1)
        by_race_out[race] = {
            "n": b["n"],
            "lab_completeness": {
                "complete_rate": round(b["complete"] / n, 4),
                "egfr_rate": round(b["has_egfr"] / n, 4),
                "lipids_rate": round(b["has_lipids"] / n, 4),
                "sbp_rate": round(b["has_sbp"] / n, 4),
            },
            "honest": {
                "show_rate": round(b["honest_show"] / n, 4),
                "refuse_rate": round(b["honest_refuse"] / n, 4),
            },
            "legacy": {
                "show_or_green_rate": round(b["legacy_show"] / n, 4),
                "white_fallback_rate_among_all": round(b["legacy_fallback"] / n, 4),
                "white_fallback_rate_among_pce_scored": (
                    round(b["legacy_fallback"] / b["legacy_pce_scored"], 4)
                    if b["legacy_pce_scored"] else None
                ),
                "pce_scored_n": b["legacy_pce_scored"],
                "under40_green_rate": round(b["legacy_under40_green"] / n, 4),
                "misattributed_equation_count": b["legacy_fallback"],
            },
            "note": (
                "RIDRETH3=6 Non-Hispanic Asian — NHANES does not separate South vs East Asian. "
                "Among PCE-scored non-White/non-AA profiles, White fallback is 1.0 by construction; "
                "NHANES contributes burden counts and honest-arm coverage cost."
            ) if race == "asian_nhanes" else (
                "Among PCE-scored non-White/non-AA profiles, White fallback is 1.0 by construction; "
                "report misattributed_equation_count as the population burden."
                if race in ("hispanic", "multiracial") else None
            ),
        }

    summary = {
        "source": "NHANES 2017-March 2020 pre-pandemic public XPT",
        "files": ["P_DEMO", "P_BPXO", "P_BMX", "P_HDL", "P_TCHOL", "P_BIOPRO", "P_SMQ", "P_DIQ", "P_BPQ"],
        "seed": SEED,
        "max_n": MAX_N,
        "n_analyzed": overall["n"],
        "overall": {
            "honest_show_rate": overall["honest_show"] / max(overall["n"], 1),
            "legacy_white_fallback_rate_among_all": overall["legacy_fallback"] / max(overall["n"], 1),
            "legacy_pce_scored_n": overall["legacy_pce_scored"],
            "legacy_white_fallback_rate_among_pce_scored": (
                overall["legacy_fallback"] / overall["legacy_pce_scored"]
                if overall["legacy_pce_scored"] else None
            ),
            "misattributed_equation_count": overall["legacy_fallback"],
            "construction_note": (
                "For races outside {white,aa}, every legacy PCE score is a White fallback by design. "
                "NHANES estimates how many people that policy would touch and honest refuse rates by stratum."
            ),
        },
        "by_race": by_race_out,
        "limitations": [
            "Cross-sectional coverage/fallback only; no mortality linkage / calibration.",
            "eGFR from serum creatinine via 2009 CKD-EPI approx for input completeness.",
            "DIQ010 / BPQ050A linked when XPT present; residual misclassification possible.",
            "Not nationally weighted point estimates (subsample + raw rates).",
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({
        "n": summary["n_analyzed"],
        "overall": {
            "honest_show": summary["overall"]["honest_show_rate"],
            "misattributed_count": summary["overall"]["misattributed_equation_count"],
            "fallback_among_pce": summary["overall"]["legacy_white_fallback_rate_among_pce_scored"],
        },
        "by_race": {k: {
            "n": v["n"],
            "complete": v["lab_completeness"]["complete_rate"],
            "honest_show": v["honest"]["show_rate"],
            "misattributed_n": v["legacy"]["misattributed_equation_count"],
            "fallback_among_pce": v["legacy"]["white_fallback_rate_among_pce_scored"],
        } for k, v in by_race_out.items()},
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
