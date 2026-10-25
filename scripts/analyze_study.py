#!/usr/bin/env python3
"""
Analyze Drift vignette study JSONL.

Healthcare-facing decisions (frequentist, prereg α=0.05):
  - Primary: two-sided Welch t on participant-mean calibrated overconfidence.
  - Decision is reject_null ONLY if p < α. Otherwise fail_to_reject_null
    ("no statistically significant evidence of an arm difference") — we do NOT
    treat every small p-near-α as an "issue," and we never invent significance.
  - Care-seeking: TOST non-inferiority (margin 0.5) — "holds" only if both
    one-sided tests reject at α.
  - Secondaries: BH-FDR across the secondary family.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
KEYS = json.loads((ROOT / "study" / "warranted_certainty.json").read_text())["keys"]

ALPHA = 0.05
CARE_NI_MARGIN = 0.5  # Likert points; prereg TOST
VIGNETTE_IDS = (
    "v1_midrisk_white",
    "v2_south_asian_same_vitals",
    "v3_under30",
    "v6_high_risk_smoker",
)


# --- numeric helpers ---------------------------------------------------------

def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def _sd(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return float("nan")
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _log_gamma(z: float) -> float:
    """Lanczos approximation for log Γ(z), z > 0."""
    # Coefficients from Numerical Recipes / Lanczos g=7
    c = [
        0.99999999999980993,
        676.5203681218851,
        -1259.1392167225429,
        771.32342877765313,
        -176.61502916214059,
        12.507343278686905,
        -0.13857109526572012,
        9.984369654078991e-6,
        1.5056327351493116e-7,
    ]
    if z < 0.5:
        # reflection: Γ(z)Γ(1-z)=π/sin(πz)
        return math.log(math.pi) - math.log(abs(math.sin(math.pi * z))) - _log_gamma(1.0 - z)
    z -= 1.0
    x = c[0]
    for i in range(1, len(c)):
        x += c[i] / (z + i)
    t = z + 7.5
    return 0.5 * math.log(2 * math.pi) + (z + 0.5) * math.log(t) - t + math.log(x)


def _betacf(a: float, b: float, x: float, max_iter: int = 200, eps: float = 3e-12) -> float:
    """Continued fraction for incomplete beta (Lentz)."""
    am, bm = 1.0, 1.0
    az = 1.0
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    bz = 1.0 - qab * x / qap
    for m in range(1, max_iter + 1):
        em = float(m)
        tem = em + em
        d = em * (b - em) * x / ((qam + tem) * (a + tem))
        ap = az + d * am
        bp = bz + d * bm
        d = -(a + em) * (qab + em) * x / ((a + tem) * (qap + tem))
        app = ap + d * az
        bpp = bp + d * bz
        am, bm, az, bz = ap / bpp, bp / bpp, app / bpp, 1.0
        if abs(az - am) < eps * abs(az):
            return az
    return az


def _betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a,b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    if a <= 0 or b <= 0:
        return float("nan")
    lbeta = _log_gamma(a) + _log_gamma(b) - _log_gamma(a + b)
    front = math.exp(math.log(max(x, 1e-300)) * a + math.log(max(1.0 - x, 1e-300)) * b - lbeta) / a
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x)
    return 1.0 - (math.exp(math.log(max(1.0 - x, 1e-300)) * b + math.log(max(x, 1e-300)) * a - lbeta) / b) * _betacf(b, a, 1.0 - x)


def student_t_cdf(t: float, df: float) -> float:
    """Two-sided-ready CDF of Student-t with `df` degrees of freedom."""
    if not math.isfinite(t) or not math.isfinite(df) or df <= 0:
        return float("nan")
    x = df / (df + t * t)
    a = 0.5 * df
    ib = _betai(a, 0.5, x)
    if t >= 0:
        return 1.0 - 0.5 * ib
    return 0.5 * ib


def student_t_ppf(p: float, df: float) -> float:
    """Approximate inverse CDF via bisection (adequate for CI critical values)."""
    if not (0.0 < p < 1.0) or df <= 0:
        return float("nan")
    if abs(p - 0.5) < 1e-15:
        return 0.0
    lo, hi = -1e6, 1e6
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if student_t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def welch_ttest(a: Sequence[float], b: Sequence[float]) -> Dict[str, float]:
    """Two-sample Welch t-test. Returns t, df, p_two_sided, mean_diff, se, ci95."""
    if len(a) < 2 or len(b) < 2:
        return {
            "t": float("nan"),
            "df": float("nan"),
            "p_two_sided": float("nan"),
            "mean_a": _mean(a),
            "mean_b": _mean(b),
            "mean_diff": _mean(a) - _mean(b),
            "se": float("nan"),
            "ci95_low": float("nan"),
            "ci95_high": float("nan"),
            "cohens_d": float("nan"),
        }
    ma, mb = _mean(a), _mean(b)
    sa, sb = _sd(a), _sd(b)
    na, nb = len(a), len(b)
    se = math.sqrt(sa ** 2 / na + sb ** 2 / nb)
    diff = ma - mb
    if se == 0.0:
        t = 0.0 if diff == 0.0 else (math.copysign(float("inf"), diff))
        df = float(na + nb - 2)
        p = 1.0 if diff == 0.0 else 0.0
        return {
            "t": t,
            "df": df,
            "p_two_sided": p,
            "mean_a": ma,
            "mean_b": mb,
            "mean_diff": diff,
            "se": 0.0,
            "ci95_low": diff,
            "ci95_high": diff,
            "cohens_d": 0.0 if diff == 0.0 else float("inf"),
        }
    t = diff / se
    num = (sa ** 2 / na + sb ** 2 / nb) ** 2
    den = (sa ** 4 / (na ** 2 * (na - 1))) + (sb ** 4 / (nb ** 2 * (nb - 1)))
    df = num / den if den else float("nan")
    # two-sided p
    cdf = student_t_cdf(abs(t), df)
    p = max(0.0, min(1.0, 2.0 * (1.0 - cdf)))
    tcrit = student_t_ppf(1.0 - ALPHA / 2.0, df)
    # pooled SD for Cohen's d (Welch-friendly: use average variance)
    sp = math.sqrt(((na - 1) * sa ** 2 + (nb - 1) * sb ** 2) / (na + nb - 2))
    d = diff / sp if sp > 0 else float("nan")
    return {
        "t": t,
        "df": df,
        "p_two_sided": p,
        "mean_a": ma,
        "mean_b": mb,
        "mean_diff": diff,
        "se": se,
        "ci95_low": diff - tcrit * se,
        "ci95_high": diff + tcrit * se,
        "cohens_d": d,
    }


def welch_tost(
    a: Sequence[float],
    b: Sequence[float],
    margin: float,
    alpha: float = ALPHA,
) -> Dict[str, Any]:
    """
    TOST equivalence/non-inferiority on mean(a)-mean(b).
    For care-seeking: a=honest, b=baseline; non-inferiority of honest means
    mean(honest) - mean(baseline) > -margin  (honest not worse by more than margin).
    We test both:
      H0_lower: diff <= -margin   vs  H1: diff > -margin
      H0_upper: diff >= +margin   vs  H1: diff < +margin  (two-sided equivalence)
    Non-inferiority (one-sided, honest not worse): only the lower bound test.
    """
    wt = welch_ttest(a, b)
    se, df, diff = wt["se"], wt["df"], wt["mean_diff"]
    if not math.isfinite(se) or se == 0.0:
        # identical arms with se=0
        holds_ni = abs(diff) <= margin if se == 0.0 and math.isfinite(diff) else False
        return {
            "margin": margin,
            "mean_diff": diff,
            "p_lower": 0.0 if (se == 0.0 and diff > -margin) else 1.0,
            "p_upper": 0.0 if (se == 0.0 and diff < margin) else 1.0,
            "noninferiority_holds": holds_ni and diff > -margin,
            "equivalence_holds": holds_ni and abs(diff) < margin,
            "note": "TOST on honest−baseline; NI = honest not worse than baseline by > margin.",
        }
    # lower: t = (diff - (-margin)) / se ; one-sided p = 1 - F(t)
    t_lo = (diff + margin) / se
    p_lo = 1.0 - student_t_cdf(t_lo, df)
    t_hi = (margin - diff) / se
    p_hi = 1.0 - student_t_cdf(t_hi, df)
    return {
        "margin": margin,
        "mean_diff": diff,
        "p_lower": max(0.0, min(1.0, p_lo)),
        "p_upper": max(0.0, min(1.0, p_hi)),
        "noninferiority_holds": p_lo < alpha,
        "equivalence_holds": (p_lo < alpha) and (p_hi < alpha),
        "note": "TOST on honest−baseline; NI holds iff p_lower < α (honest not worse by > margin).",
    }


def bh_fdr(pvals: Dict[str, float], alpha: float = ALPHA) -> Dict[str, Any]:
    """Benjamini–Hochberg. Returns reject flags; empty/NaN p → not rejected."""
    items = [(k, p) for k, p in pvals.items() if p is not None and math.isfinite(p)]
    m = len(items)
    if m == 0:
        return {"alpha": alpha, "rejects": {k: False for k in pvals}, "adjusted": {}}
    items.sort(key=lambda kv: kv[1])
    adj: Dict[str, float] = {}
    rejects: Dict[str, bool] = {k: False for k in pvals}
    prev = 1.0
    # compute adjusted from largest to smallest rank
    ranked = list(enumerate(items, start=1))
    adj_list = [0.0] * m
    for i in range(m - 1, -1, -1):
        rank, (name, p) = ranked[i]
        val = min(prev, p * m / rank)
        adj_list[i] = val
        prev = val
    for i, (name, _p) in enumerate(items):
        adj[name] = adj_list[i]
        rejects[name] = adj_list[i] <= alpha
    return {"alpha": alpha, "rejects": rejects, "adjusted": adj}


def primary_decision(p_two_sided: float, alpha: float = ALPHA) -> Dict[str, Any]:
    """Explicit NHST decision — no soft 'small chance' hedging."""
    if not math.isfinite(p_two_sided):
        return {
            "alpha": alpha,
            "reject_null": False,
            "decision": "insufficient_data",
            "plain_language": "Not enough data to test the primary endpoint.",
        }
    if p_two_sided < alpha:
        return {
            "alpha": alpha,
            "reject_null": True,
            "decision": "reject_null_arm_difference",
            "plain_language": (
                f"Statistically significant arm difference at α={alpha} "
                f"(two-sided p={p_two_sided:.4g})."
            ),
        }
    return {
        "alpha": alpha,
        "reject_null": False,
        "decision": "fail_to_reject_null_no_issue_flagged",
        "plain_language": (
            f"No statistically significant evidence of an arm difference at α={alpha} "
            f"(two-sided p={p_two_sided:.4g}). Primary null not rejected — "
            f"do not treat this as an 'issue' or as proof of equivalence."
        ),
    }


# --- data loading ------------------------------------------------------------

def warranted(vid: str, arm: str = "") -> float:
    """Arm-independent vignette keys (avoids encoding the hypothesis into the DV)."""
    if vid in KEYS and not isinstance(KEYS[vid], dict):
        return float(KEYS[vid])
    block = KEYS.get(vid)
    if isinstance(block, dict):
        if arm in block:
            return float(block[arm])
        return float(next(iter(block.values())))
    for k, v in KEYS.items():
        if vid.startswith(str(k).split("_")[0]) or str(k).startswith(vid):
            if not isinstance(v, dict):
                return float(v)
    return 4.0


def load_obs(path: Path) -> List[dict]:
    files = list(path.glob("*.jsonl")) + list(path.glob("*.json")) if path.is_dir() else [path]
    obs: List[dict] = []
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
                        row["prolific_id"] = (
                            row.get("prolific_id") or payload.get("prolific_id") or payload.get("pid")
                        )
                        row["attention_ok_parent"] = payload.get("attention_ok")
                        obs.append(row)
                else:
                    obs.append(payload)
    return obs


def analyze_observations(raw: Iterable[dict], *, alpha: float = ALPHA) -> Dict[str, Any]:
    by_pid: Dict[str, List[dict]] = defaultdict(list)
    n_excl_attn = 0
    for o in raw:
        if o.get("attention_ok") is False or o.get("attention_ok_parent") is False:
            n_excl_attn += 1
            continue
        if o.get("arm") not in ("honest", "baseline"):
            continue
        by_pid[str(o.get("prolific_id") or "anon")].append(o)

    arm_scores: Dict[str, List[float]] = defaultdict(list)
    care_v6: Dict[str, List[float]] = defaultdict(list)
    comp: Dict[str, List[float]] = defaultdict(list)

    for _pid, rows in by_pid.items():
        if not rows:
            continue
        arm = rows[0]["arm"]
        calibrated = []
        for r in rows:
            oc = r.get("overconfidence")
            if oc is None:
                continue
            calibrated.append(float(oc) - warranted(str(r.get("vignette") or ""), arm))
            if str(r.get("vignette") or "").startswith("v6") and r.get("care_seeking") is not None:
                care_v6[arm].append(float(r["care_seeking"]))
            if r.get("mc_race_correct") is not None:
                comp[arm].append(1.0 if r["mc_race_correct"] else 0.0)
            if r.get("mc_health_age_correct") is not None:
                comp[arm].append(1.0 if r["mc_health_age_correct"] else 0.0)
        if calibrated:
            arm_scores[arm].append(_mean(calibrated))

    primary = welch_ttest(arm_scores["honest"], arm_scores["baseline"])
    decision = primary_decision(primary["p_two_sided"], alpha=alpha)

    care_test = welch_ttest(care_v6["honest"], care_v6["baseline"])
    care_tost = welch_tost(care_v6["honest"], care_v6["baseline"], CARE_NI_MARGIN, alpha=alpha)
    comp_test = welch_ttest(comp["honest"], comp["baseline"])

    secondary_p = {
        "comprehension": comp_test["p_two_sided"],
        "care_seeking_difference": care_test["p_two_sided"],
    }
    fdr = bh_fdr(secondary_p, alpha=alpha)

    n_part = len(arm_scores["honest"]) + len(arm_scores["baseline"])
    return {
        "n_participants": n_part,
        "n_honest": len(arm_scores["honest"]),
        "n_baseline": len(arm_scores["baseline"]),
        "n_excluded_attention": n_excl_attn,
        "alpha": alpha,
        "primary_calibrated_overconfidence": {
            "honest_mean": primary["mean_a"],
            "baseline_mean": primary["mean_b"],
            "delta_honest_minus_baseline": primary["mean_diff"],
            "welch_t": primary["t"],
            "welch_df": primary["df"],
            "p_two_sided": primary["p_two_sided"],
            "ci95": [primary["ci95_low"], primary["ci95_high"]],
            "cohens_d": primary["cohens_d"],
            "unit": "participant",
            "note": "Negative delta = honest less overconfident (desired direction).",
            **decision,
        },
        "secondary_comprehension": {
            "honest_mean": _mean(comp["honest"]),
            "baseline_mean": _mean(comp["baseline"]),
            "p_two_sided": comp_test["p_two_sided"],
            "bh_reject": fdr["rejects"].get("comprehension", False),
            "bh_adjusted_p": fdr["adjusted"].get("comprehension"),
        },
        "secondary_care_seeking_v6": {
            "honest_mean": _mean(care_v6["honest"]),
            "baseline_mean": _mean(care_v6["baseline"]),
            "p_two_sided_difference": care_test["p_two_sided"],
            "bh_reject_difference": fdr["rejects"].get("care_seeking_difference", False),
            "tost": care_tost,
            "plain_language": (
                "Care-seeking non-inferiority holds."
                if care_tost["noninferiority_holds"]
                else "Care-seeking non-inferiority NOT established (do not claim safety on this endpoint)."
            ),
        },
        "secondary_fdr": fdr,
        "status": "confirmatory" if n_part >= 500 else ("pilot" if n_part >= 20 else "insufficient"),
        "interpretation_rules": {
            "primary": "Flag an arm-difference issue only if reject_null is true (p < α). Otherwise: no issue flagged.",
            "care_seeking": "Safety claim only if TOST noninferiority_holds is true.",
            "no_probabilistic_hedging": "p-values are not 'chances the null is true'; decisions are binary at α.",
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "facct" / "human_study_results.json")
    ap.add_argument("--alpha", type=float, default=ALPHA)
    args = ap.parse_args()

    summary = analyze_observations(load_obs(args.input), alpha=args.alpha)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
