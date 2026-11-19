#!/usr/bin/env python3
"""
Recompute intra-rater agreement / Cohen's κ from stored pass1/pass2
scores in docs/facct/external_calculator_audit.json.

This is SAME-CODER delayed re-score reliability — NOT dual-coder κ.
Does not invent screenshots or fetch live pages.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT = ROOT / "docs" / "facct" / "external_calculator_audit.json"


def cohens_kappa_binary(y1: Sequence[bool], y2: Sequence[bool]) -> Dict[str, Any]:
    """Cohen's κ for two dichotomous coder passes (or same-coder passes)."""
    if len(y1) != len(y2):
        raise ValueError("pass lengths differ")
    n = len(y1)
    if n == 0:
        return {
            "n": 0,
            "agreement_rate": None,
            "cohens_kappa": None,
            "note": "empty",
        }

    a = b = c = d = 0  # both Y; p1Y p2N; p1N p2Y; both N
    for p1, p2 in zip(y1, y2):
        if p1 and p2:
            a += 1
        elif p1 and not p2:
            b += 1
        elif (not p1) and p2:
            c += 1
        else:
            d += 1

    agree = a + d
    p_o = agree / n
    p1_yes = a + b
    p2_yes = a + c
    p1_no = c + d
    p2_no = b + d
    p_e = ((p1_yes * p2_yes) + (p1_no * p2_no)) / (n * n)

    if abs(1.0 - p_e) < 1e-12:
        kappa: Optional[float] = None
        kappa_note = "undefined: expected agreement p_e == 1 (no variance)"
    else:
        kappa = (p_o - p_e) / (1.0 - p_e)
        kappa_note = None
        # κ paradox: high agreement but κ near 0 when base rates extreme
        if p_o >= 0.8 and kappa is not None and kappa < 0.4:
            kappa_note = (
                "kappa paradox: high observed agreement with extreme class imbalance; "
                "report agreement_rate alongside κ"
            )

    return {
        "n": n,
        "contingency": {
            "both_yes": a,
            "pass1_yes_pass2_no": b,
            "pass1_no_pass2_yes": c,
            "both_no": d,
        },
        "agreement_rate": round(p_o, 6),
        "p_e": round(p_e, 6),
        "cohens_kappa": None if kappa is None else round(kappa, 6),
        "note": kappa_note,
        "label": "intra_rater_not_dual_coder",
    }


def _tool_passes(tool: Dict[str, Any], keys: Sequence[str]) -> Tuple[List[bool], List[bool]]:
    p1 = tool.get("pass1") or {}
    p2 = tool.get("pass2") or {}
    y1 = [bool(p1[k]) for k in keys]
    y2 = [bool(p2[k]) for k in keys]
    return y1, y2


def evaluate(audit: Dict[str, Any]) -> Dict[str, Any]:
    keys: List[str] = list(audit["keys"])
    tools: List[Dict[str, Any]] = list(audit["tools"])

    per_key: Dict[str, Any] = {}
    for k in keys:
        y1 = [bool(t["pass1"][k]) for t in tools]
        y2 = [bool(t["pass2"][k]) for t in tools]
        per_key[k] = cohens_kappa_binary(y1, y2)

    flat1: List[bool] = []
    flat2: List[bool] = []
    disagreements: List[Dict[str, str]] = []
    for t in tools:
        y1, y2 = _tool_passes(t, keys)
        flat1.extend(y1)
        flat2.extend(y2)
        for k, a, b in zip(keys, y1, y2):
            if a != b:
                disagreements.append(
                    {
                        "tool": t["name"],
                        "key": k,
                        "pass1": str(a),
                        "pass2": str(b),
                    }
                )

    overall = cohens_kappa_binary(flat1, flat2)
    return {
        "reliability_type": "intra_rater_delayed_rescore",
        "not_dual_coder_kappa": True,
        "n_tools": len(tools),
        "n_keys": len(keys),
        "n_item_pairs": len(flat1),
        "disagreements": disagreements,
        "per_key": per_key,
        "overall": overall,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--audit",
        type=Path,
        default=DEFAULT_AUDIT,
        help="Path to external_calculator_audit.json",
    )
    ap.add_argument(
        "--write-back",
        action="store_true",
        help="Replace audit['intra_rater_reliability']['metrics'] with recomputed values",
    )
    args = ap.parse_args()

    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    metrics = evaluate(audit)

    if args.write_back:
        block = audit.setdefault("intra_rater_reliability", {})
        block["metrics"] = metrics
        args.audit.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
        print(f"wrote metrics → {args.audit}", file=sys.stderr)

    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
