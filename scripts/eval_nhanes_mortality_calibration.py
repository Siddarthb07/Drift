#!/usr/bin/env python3
"""
Attempt crude mortality calibration on NHANES 2011–2012 + public LMF (through 2019).

Honest scope: CVD-coded mortality (UCOD leading heart disease / cerebrovascular),
not adjudicated ASCVD events; PREVENT/PCE are event models. Report discrimination
and mean calibration only as a feasibility probe — not a definitive validation.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DATA = ROOT / "data" / "nhanes_lmf"
OUT = ROOT / "docs" / "facct" / "nhanes_mortality_calibration.json"

from prevent_equations import prevent_10yr  # noqa: E402
from risk_calculators import pooled_cohort_cvd_10yr  # noqa: E402


def _read_xpt(name: str) -> pd.DataFrame:
    return pd.read_sas(DATA / name, format="xport")


def _egfr(scr: float, age: float, female: bool) -> float:
    # 2021 race-free CKD-EPI creatinine
    kappa = 0.7 if female else 0.9
    alpha = -0.241 if female else -0.302
    scr_k = scr / kappa
    return float(
        142
        * (min(scr_k, 1) ** alpha)
        * (max(scr_k, 1) ** -1.200)
        * (0.9938 ** age)
        * (1.012 if female else 1.0)
    )


def parse_lmf(path: Path) -> pd.DataFrame:
    """NCHS public-use linked mortality fixed-width (2019 public release)."""
    rows = []
    for line in path.read_text(errors="replace").splitlines():
        if len(line) < 40:
            continue
        try:
            seqn = int(line[0:6])
        except ValueError:
            continue
        elig = line[14:15].strip()
        mort = line[15:16].strip()
        ucod = line[16:19].strip()
        permth = line[37:40].strip()
        rows.append(
            {
                "SEQN": seqn,
                "ELIGSTAT": int(elig) if elig.isdigit() else None,
                "MORTSTAT": int(mort) if mort.isdigit() else None,
                "UCOD_LEADING": ucod,
                "PERMTH_EXM": int(permth) if permth.isdigit() else None,
            }
        )
    return pd.DataFrame(rows)


def _auc(scores: np.ndarray, events: np.ndarray) -> float | None:
    pos = scores[events == 1]
    neg = scores[events == 0]
    if len(pos) == 0 or len(neg) == 0:
        return None
    # Mann–Whitney
    correct = 0.0
    for p in pos:
        correct += np.sum(neg < p) + 0.5 * np.sum(neg == p)
    return float(correct / (len(pos) * len(neg)))


def main() -> int:
    if not (DATA / "NHANES_2011_2012_MORT_2019_PUBLIC.dat").exists():
        print("missing LMF", file=sys.stderr)
        return 1
    demo = _read_xpt("DEMO_G.xpt")
    bpx = _read_xpt("BPX_G.xpt")
    bmx = _read_xpt("BMX_G.xpt")
    tchol = _read_xpt("TCHOL_G.xpt")
    hdl = _read_xpt("HDL_G.xpt")
    bio = _read_xpt("BIOPRO_G.xpt")
    smq = _read_xpt("SMQ_G.xpt") if (DATA / "SMQ_G.xpt").exists() else None
    diq = _read_xpt("DIQ_G.xpt") if (DATA / "DIQ_G.xpt").exists() else None
    bpq = _read_xpt("BPQ_G.xpt") if (DATA / "BPQ_G.xpt").exists() else None
    lmf = parse_lmf(DATA / "NHANES_2011_2012_MORT_2019_PUBLIC.dat")

    df = demo.merge(bpx, on="SEQN", how="left")
    df = df.merge(bmx, on="SEQN", how="left")
    df = df.merge(tchol, on="SEQN", how="left")
    df = df.merge(hdl, on="SEQN", how="left")
    df = df.merge(bio, on="SEQN", how="left")
    for extra in (smq, diq, bpq):
        if extra is not None:
            df = df.merge(extra, on="SEQN", how="left")
    df = df.merge(lmf, on="SEQN", how="inner")

    records = []
    for _, row in df.iterrows():
        age = float(row.get("RIDAGEYR") or 0)
        if not (40 <= age <= 79):
            continue
        if row.get("ELIGSTAT") != 1:
            continue
        sex_code = int(row.get("RIAGENDR") or 0)
        if sex_code not in (1, 2):
            continue
        female = sex_code == 2
        sex = "female" if female else "male"
        race3 = int(row.get("RIDRETH3") or 0)
        # PCE-valid races only for fair PCE arm
        if race3 == 3:
            race = "aa"
        elif race3 == 4:
            race = "white"
        else:
            race = None
        sbps = [row.get(c) for c in ("BPXSY1", "BPXSY2", "BPXSY3") if c in row.index]
        sbps = [float(x) for x in sbps if x == x and x is not None]
        sbp = float(np.mean(sbps)) if sbps else None
        tc = float(row["LBXTC"]) if row.get("LBXTC") == row.get("LBXTC") else None
        hdlv = float(row["LBDHDD"]) if "LBDHDD" in row.index and row.get("LBDHDD") == row.get("LBDHDD") else None
        if hdlv is None and "LBDHDL" in row.index and row.get("LBDHDL") == row.get("LBDHDL"):
            hdlv = float(row["LBDHDL"])
        scr = float(row["LBXSCR"]) if row.get("LBXSCR") == row.get("LBXSCR") else None
        ht = float(row["BMXHT"]) if row.get("BMXHT") == row.get("BMXHT") else None
        wt = float(row["BMXWT"]) if row.get("BMXWT") == row.get("BMXWT") else None
        bmi = (wt / ((ht / 100) ** 2)) if ht and wt else None
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
        if None in (sbp, tc, hdlv, scr, bmi):
            continue
        egfr = _egfr(scr, age, female)
        if not (15 <= egfr <= 140 and 90 <= sbp <= 200 and 130 <= tc <= 320 and 20 <= hdlv <= 100):
            continue
        # Outcomes: leading cause heart disease (001) or cerebrovascular (005)
        ucod = str(row.get("UCOD_LEADING") or "")
        mort = int(row.get("MORTSTAT") or 0) == 1
        cvd_death = mort and ucod in ("001", "005")
        w = float(row.get("WTMEC2YR") or row.get("WTINT2YR") or 1.0)
        if w <= 0:
            continue

        pce = None
        if race in ("white", "aa"):
            pce = pooled_cohort_cvd_10yr(
                age, sex, tc, hdlv, sbp, bp_meds, smoker, diabetes, race=race
            )
        prev = prevent_10yr(
            sex=sex,
            age=age,
            total_chol=tc,
            hdl_chol=hdlv,
            sbp=sbp,
            diabetes=diabetes,
            current_smoker=smoker,
            bmi=bmi,
            egfr=egfr,
            bp_treated=bp_meds,
            outcome="ascvd",
        )
        records.append(
            {
                "wt": w,
                "cvd_death": int(cvd_death),
                "pce": None if pce is None else float(pce["risk_pct"]) / 100.0,
                "prevent": None if prev is None else float(prev["risk_pct"]) / 100.0,
                "race": race,
            }
        )

    recs = [r for r in records if r["prevent"] is not None]
    both = [r for r in recs if r["pce"] is not None]
    def summarize(name: str, key: str, subset: list) -> dict:
        y = np.array([r["cvd_death"] for r in subset], dtype=float)
        s = np.array([r[key] for r in subset], dtype=float)
        w = np.array([r["wt"] for r in subset], dtype=float)
        obs = float(np.average(y, weights=w))
        pred = float(np.average(s, weights=w))
        return {
            "n": len(subset),
            "events": int(y.sum()),
            "weighted_event_rate": round(obs, 4),
            "weighted_mean_predicted": round(pred, 4),
            "calibration_ratio_pred_over_obs": (
                None if obs <= 0 else round(pred / obs, 3)
            ),
            "auc_unweighted": None if _auc(s, y) is None else round(_auc(s, y), 3),
        }

    out = {
        "cycle": "NHANES 2011–2012",
        "lmf": "NHANES_2011_2012_MORT_2019_PUBLIC.dat",
        "outcome": "Leading-cause CVD mortality (UCOD 001 heart / 005 cerebrovascular)",
        "scope_note": (
            "Feasibility probe only. PREVENT/PCE predict ASCVD events, not leading-cause "
            "mortality; public LMF lacks adjudicated ASCVD. Not a claim of clinical validation."
        ),
        "eligibility": "Ages 40–79, ELIGSTAT=1, complete labs within PREVENT hard ranges",
        "prevent_all_races_in_range": summarize("prevent", "prevent", recs),
        "paired_white_aa": {
            "prevent": summarize("prevent", "prevent", both),
            "pce": summarize("pce", "pce", both),
        },
        "n_scored_prevent": len(recs),
        "n_scored_paired_white_aa": len(both),
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
