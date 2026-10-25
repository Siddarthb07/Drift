#!/usr/bin/env python3
"""Analyze Drift vignette study JSONL. Arm must be on each trial (collector stamps it)."""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEYS = json.loads((ROOT / "study" / "warranted_certainty.json").read_text())["keys"]


def _mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def _sd(xs):
    if len(xs) < 2:
        return float("nan")
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _welch_t(a, b):
    if len(a) < 2 or len(b) < 2:
        return float("nan"), float("nan")
    ma, mb = _mean(a), _mean(b)
    sa, sb = _sd(a), _sd(b)
    na, nb = len(a), len(b)
    se = math.sqrt(sa ** 2 / na + sb ** 2 / nb)
    if se == 0:
        return float("nan"), float("nan")
    t = (ma - mb) / se
    num = (sa ** 2 / na + sb ** 2 / nb) ** 2
    den = (sa ** 4 / (na ** 2 * (na - 1))) + (sb ** 4 / (nb ** 2 * (nb - 1)))
    df = num / den if den else float("nan")
    return t, df


def load_obs(path: Path):
    files = list(path.glob("*.jsonl")) + list(path.glob("*.json")) if path.is_dir() else [path]
    obs = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        if f.suffix == ".jsonl" or text.lstrip().startswith("{"):
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                arm = payload.get("arm")
                if "responses" in payload:
                    for r in payload["responses"]:
                        row = dict(r)
                        row["arm"] = row.get("arm") or arm
                        row["prolific_id"] = row.get("prolific_id") or payload.get("prolific_id") or payload.get("pid")
                        row["attention_ok_parent"] = payload.get("attention_ok")
                        obs.append(row)
                else:
                    obs.append(payload)
    return obs


def warranted(vid: str, arm: str = "") -> float:
    """Arm-independent vignette keys (avoids encoding the hypothesis into the DV)."""
    if vid in KEYS and not isinstance(KEYS[vid], dict):
        return float(KEYS[vid])
    block = KEYS.get(vid)
    if isinstance(block, dict):
        # legacy shape during transition
        if arm in block:
            return float(block[arm])
        return float(next(iter(block.values())))
    for k, v in KEYS.items():
        if vid.startswith(str(k).split("_")[0]) or str(k).startswith(vid):
            if not isinstance(v, dict):
                return float(v)
    return 4.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "facct" / "human_study_results.json")
    args = ap.parse_args()

    raw = load_obs(args.input)
    # Exclusions
    by_pid = defaultdict(list)
    for o in raw:
        if o.get("arm") not in ("honest", "baseline"):
            continue
        if o.get("attention_ok") is False:
            continue
        by_pid[o.get("prolific_id") or "anon"].append(o)

    # participant-level primary
    arm_scores = defaultdict(list)
    care_v6 = defaultdict(list)
    comp = defaultdict(list)
    n_excl_attn = sum(1 for o in raw if o.get("attention_ok") is False)

    for pid, rows in by_pid.items():
        if not rows:
            continue
        arm = rows[0]["arm"]
        calibrated = []
        for r in rows:
            oc = r.get("overconfidence")
            if oc is None:
                continue
            calibrated.append(float(oc) - warranted(str(r.get("vignette") or ""), arm))
            if str(r.get("vignette") or "").startswith("v6"):
                care_v6[arm].append(float(r.get("care_seeking") or 0))
            if r.get("mc_race_correct") is not None:
                comp[arm].append(1.0 if r["mc_race_correct"] else 0.0)
            if r.get("mc_health_age_correct") is not None:
                comp[arm].append(1.0 if r["mc_health_age_correct"] else 0.0)
        if calibrated:
            arm_scores[arm].append(_mean(calibrated))

    t, df = _welch_t(arm_scores["honest"], arm_scores["baseline"])
    n_part = len(arm_scores["honest"]) + len(arm_scores["baseline"])
    summary = {
        "n_participants": n_part,
        "n_honest": len(arm_scores["honest"]),
        "n_baseline": len(arm_scores["baseline"]),
        "n_excluded_attention": n_excl_attn,
        "primary_calibrated_overconfidence": {
            "honest_mean": _mean(arm_scores["honest"]),
            "baseline_mean": _mean(arm_scores["baseline"]),
            "delta_honest_minus_baseline": _mean(arm_scores["honest"]) - _mean(arm_scores["baseline"]),
            "welch_t": t,
            "welch_df": df,
            "unit": "participant",
            "note": "Negative delta = honest less overconfident (desired).",
        },
        "secondary_comprehension": {
            "honest_mean": _mean(comp["honest"]),
            "baseline_mean": _mean(comp["baseline"]),
        },
        "secondary_care_seeking_v6": {
            "honest_mean": _mean(care_v6["honest"]),
            "baseline_mean": _mean(care_v6["baseline"]),
        },
        "status": "confirmatory" if n_part >= 500 else ("pilot" if n_part >= 20 else "insufficient"),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
