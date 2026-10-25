#!/usr/bin/env python3
"""Document that legacy_baseline mirrors pre-fix behaviors at a pinned SHA."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = "a8dcc33"
OUT = ROOT / "docs" / "facct" / "baseline_git_pin.json"


def _from_git() -> dict:
    show = subprocess.check_output(
        ["git", "show", f"{PIN}:app_v5.py"],
        cwd=ROOT,
        text=True,
        errors="replace",
    )
    checks = {
        "silent_waist_94_80": "or (94 if sex == \"male\" else 80)" in show,
        "silent_sbp_120": "or 120)" in show and "systolic" in show,
        "under_40_green": "Under 40" in show,
        "health_age_call": "estimate_health_age" in show,
        "race_default_white": 'user.get("race", "white")' in show,
    }
    subject = subprocess.check_output(
        ["git", "log", "-1", "--format=%s", PIN], cwd=ROOT, text=True
    ).strip()
    return {
        "pin_sha": PIN,
        "pin_subject": subject,
        "behaviors_present_in_pin": checks,
        "all_present": all(checks.values()),
        "legacy_module": "legacy_baseline.py",
        "source": "git",
        "note": "Baseline arm reconstructs these disclosure behaviors; PCE math uses corrected coeffs.",
    }


def main() -> int:
    try:
        out = _from_git()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        if not OUT.exists():
            print(f"FAIL: no git history and no committed pin JSON ({exc})")
            return 1
        out = json.loads(OUT.read_text())
        out["source"] = "committed_json_fallback"
        out["fallback_reason"] = str(exc)
        if not out.get("all_present"):
            print(json.dumps(out, indent=2))
            return 1
        print(json.dumps(out, indent=2))
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0 if out["all_present"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
