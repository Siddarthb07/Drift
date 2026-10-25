#!/usr/bin/env python3
"""
Analyze Drift vignette study JSONL (Prolific / local collector).

Primary: overconfidence (1–7) honest vs baseline.
Secondary: comprehension %; care-seeking on high-risk vignette (v6).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Warranted certainty keys (clinician-pre-specified placeholders; update after dual coding)
WARRANTED = {
    "v1": 4, "v2": 4, "v3": 2, "v4": 3, "v5": 2, "v6": 5,
    # survey short ids
}


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
    # Welch–Satterthwaite df
    num = (sa ** 2 / na + sb ** 2 / nb) ** 2
    den = (sa ** 4 / (na ** 2 * (na - 1))) + (sb ** 4 / (nb ** 2 * (nb - 1)))
    df = num / den if den else float("nan")
    return t, df


def load_rows(path: Path):
    rows = []
    if path.is_dir():
        files = list(path.glob("*.json")) + list(path.glob("*.jsonl"))
    else:
        files = [path]
    for f in files:
        text = f.read_text(encoding="utf-8")
        if f.suffix == ".jsonl" or "\n{" in text:
            for line in text.splitlines():
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        else:
            payload = json.loads(text)
            if isinstance(payload, list):
                rows.extend(payload)
            elif "responses" in payload:
                for r in payload["responses"]:
                    rows.append({**r, "completion_code": payload.get("completion_code")})
            else:
                rows.append(payload)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path, help="JSON/JSONL file or directory")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "facct" / "human_study_results.json")
    args = ap.parse_args()

    raw = load_rows(args.input)
    if not raw:
        print("No rows found", file=sys.stderr)
        return 1

    # Flatten response-level
    obs = []
    for r in raw:
        if "responses" in r:
            for x in r["responses"]:
                obs.append(x)
        else:
            obs.append(r)

    by_arm = defaultdict(list)
    care_v6 = defaultdict(list)
    comp = defaultdict(list)

    for o in obs:
        arm = o.get("arm")
        if arm not in ("honest", "baseline"):
            continue
        oc = o.get("overconfidence")
        if oc is None:
            continue
        vid = str(o.get("vignette") or "")
        warranted = WARRANTED.get(vid, 4)
        calibrated = float(oc) - warranted
        by_arm[arm].append(calibrated)
        if vid in ("v6", "v6_high_risk") or "high" in vid:
            care_v6[arm].append(float(o.get("care_seeking") or 0))
        correct = 0
        nq = 0
        if "mc_south_asian_correct" in o:
            nq += 1
            correct += int(bool(o["mc_south_asian_correct"]))
        if "mc_health_age_correct" in o:
            nq += 1
            correct += int(bool(o["mc_health_age_correct"]))
        if nq:
            comp[arm].append(correct / nq)

    t, df = _welch_t(by_arm["honest"], by_arm["baseline"])
    summary = {
        "n_observations": len(obs),
        "n_honest": len(by_arm["honest"]),
        "n_baseline": len(by_arm["baseline"]),
        "primary_overconfidence_minus_warranted": {
            "honest_mean": _mean(by_arm["honest"]),
            "baseline_mean": _mean(by_arm["baseline"]),
            "delta_honest_minus_baseline": _mean(by_arm["honest"]) - _mean(by_arm["baseline"]),
            "welch_t": t,
            "welch_df": df,
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
        "status": "confirmatory" if len(by_arm["honest"]) >= 100 else "pilot_or_insufficient",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
