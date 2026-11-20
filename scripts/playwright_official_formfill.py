#!/usr/bin/env python3
"""A3 form-fill: drive ACC Estimator Plus (+ AHA PREVENT entry) across a fixed profile grid.

Fills official calculator forms (not landing-page only), extracts caveat regex + numerics,
saves DOM/PNG with SHA-256. Reference behavior = what official tools refuse/caveat.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "jbhi" / "outside_corpus" / "playwright_formfill"
OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT = ROOT / "docs" / "jbhi" / "outside_corpus" / "playwright_formfill_report.json"

CAVEAT_RE = re.compile(
    r"(other|white equation|caveat|not validated|under.?estimat|over.?estimat|"
    r"race.?free|apply.?white|may not apply|disclaimer|limitation|coverage|"
    r"outside|out of range|not indicated|cannot calculate|unable to)",
    re.I,
)
NUM_RE = re.compile(r"(\d{1,2}(?:\.\d+)?)\s*%")
REFUSE_RE = re.compile(r"(cannot|unable|not (able|indicated|valid)|out of range|outside (the )?range|error)", re.I)

PROFILES = [
    {"tag": "pce_wf", "age": 55, "sex": "Female", "race": "White", "tc": 213, "hdl": 50, "sbp": 120,
     "bp_tx": False, "smoker": False, "diabetes": False, "bmi": 25.0, "egfr": 90},
    {"tag": "pce_wm", "age": 55, "sex": "Male", "race": "White", "tc": 213, "hdl": 50, "sbp": 120,
     "bp_tx": False, "smoker": False, "diabetes": False, "bmi": 25.0, "egfr": 90},
    {"tag": "other_race", "age": 55, "sex": "Female", "race": "Other", "tc": 213, "hdl": 50, "sbp": 120,
     "bp_tx": False, "smoker": False, "diabetes": False, "bmi": 25.0, "egfr": 90},
    {"tag": "missing_hint_low_hdl", "age": 55, "sex": "Female", "race": "White", "tc": 213, "hdl": 15, "sbp": 120,
     "bp_tx": False, "smoker": False, "diabetes": False, "bmi": 25.0, "egfr": 90},
    {"tag": "oor_sbp", "age": 55, "sex": "Female", "race": "White", "tc": 213, "hdl": 50, "sbp": 220,
     "bp_tx": False, "smoker": False, "diabetes": False, "bmi": 25.0, "egfr": 90},
]


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def fill_by_placeholder(page, placeholder: str, value: Any) -> bool:
    loc = page.locator(f'input[placeholder="{placeholder}"]')
    if loc.count() == 0:
        return False
    loc.first.fill("")
    loc.first.fill(str(value))
    return True


def click_text(page, text: str) -> bool:
    loc = page.get_by_text(text, exact=True)
    if loc.count() == 0:
        loc = page.get_by_role("button", name=re.compile(re.escape(text), re.I))
    if loc.count() == 0:
        return False
    try:
        loc.first.click(timeout=5000)
        return True
    except Exception:
        return False


def audit_acc(page, profile: Dict[str, Any]) -> Dict[str, Any]:
    url = "https://tools.acc.org/ASCVD-Risk-Estimator-Plus/#!/calculate/estimate/"
    page.goto(url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(3500)
    # Prefer Pooled Cohort mode for race/Other behavior
    click_text(page, "Pooled Cohort")
    page.wait_for_timeout(800)
    fill_by_placeholder(page, "30-79 yrs", profile["age"])
    fill_by_placeholder(page, "20-100 mg/dL", profile["hdl"])
    fill_by_placeholder(page, "130-320 mg/dL", profile["tc"])
    fill_by_placeholder(page, "90-200 mmHg", profile["sbp"])
    # optional PREVENT fields if visible
    fill_by_placeholder(page, "18.5-39.9 kg/m²", profile["bmi"])
    fill_by_placeholder(page, "15-140", profile["egfr"])
    # Sex / race: try button labels
    click_text(page, profile["sex"])
    # Race labels vary; try common ACC wording
    race = profile["race"]
    for cand in (race, "White", "Black", "Other", "African American"):
        if race == "Other" and cand in ("White", "Black", "African American"):
            continue
        if race == "White" and cand in ("Black", "African American", "Other"):
            continue
        if click_text(page, cand):
            break
    if race == "Other":
        click_text(page, "Other")
    click_text(page, "Calculate")
    page.wait_for_timeout(2500)
    text = page.inner_text("body")
    snap = OUT_DIR / f"acc_{profile['tag']}.dom.html"
    shot = OUT_DIR / f"acc_{profile['tag']}.png"
    snap.write_text(page.content())
    page.screenshot(path=str(shot), full_page=True)
    nums = [float(x) for x in NUM_RE.findall(text)]
    return {
        "tool": "acc_estimator_plus",
        "profile": profile["tag"],
        "url": page.url,
        "has_caveat_string": bool(CAVEAT_RE.search(text)),
        "appears_refused": bool(REFUSE_RE.search(text)) and len(nums) == 0,
        "numbers_pct_found": nums[:15],
        "text_len": len(text),
        "dom_sha256": sha256_file(snap),
        "png_sha256": sha256_file(shot),
        "status": "ok",
    }


def audit_aha_prevent_entry(page, profile: Dict[str, Any]) -> Dict[str, Any]:
    """AHA PREVENT often lands on a gateway; follow calculator links if present."""
    url = "https://professional.heart.org/en/guidelines-and-statements/prevent-calculator"
    row: Dict[str, Any] = {"tool": "aha_prevent", "profile": profile["tag"], "url": url}
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(3000)
        # Follow obvious calculator CTAs
        for label in ("Launch", "Open", "Calculate", "PREVENT", "Start"):
            if click_text(page, label):
                page.wait_for_timeout(2000)
                break
        # Try ACC CVD Risk Estimator PREVENT mode as the operational AHA path
        if "acc.org" not in page.url and "heart.org" in page.url:
            page.goto("https://tools.acc.org/ASCVD-Risk-Estimator-Plus/#!/calculate/estimate/",
                      wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(3000)
        click_text(page, "PREVENT")
        page.wait_for_timeout(800)
        fill_by_placeholder(page, "30-79 yrs", profile["age"])
        fill_by_placeholder(page, "20-100 mg/dL", profile["hdl"])
        fill_by_placeholder(page, "130-320 mg/dL", profile["tc"])
        fill_by_placeholder(page, "90-200 mmHg", profile["sbp"])
        fill_by_placeholder(page, "18.5-39.9 kg/m²", profile["bmi"])
        fill_by_placeholder(page, "15-140", profile["egfr"])
        click_text(page, profile["sex"])
        click_text(page, "Calculate")
        page.wait_for_timeout(2500)
        text = page.inner_text("body")
        snap = OUT_DIR / f"aha_{profile['tag']}.dom.html"
        shot = OUT_DIR / f"aha_{profile['tag']}.png"
        snap.write_text(page.content())
        page.screenshot(path=str(shot), full_page=True)
        nums = [float(x) for x in NUM_RE.findall(text)]
        row.update({
            "url": page.url,
            "has_caveat_string": bool(CAVEAT_RE.search(text)),
            "appears_refused": bool(REFUSE_RE.search(text)) and len(nums) == 0,
            "numbers_pct_found": nums[:15],
            "text_len": len(text),
            "dom_sha256": sha256_file(snap),
            "png_sha256": sha256_file(shot),
            "status": "ok",
            "note": "Filled via ACC Estimator PREVENT mode when AHA page is a gateway",
        })
    except Exception as e:
        row.update({"status": "error", "error": f"{type(e).__name__}: {e}"})
    return row


def main() -> int:
    from playwright.sync_api import sync_playwright

    ts = datetime.now(timezone.utc).isoformat()
    results: List[Dict[str, Any]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        for prof in PROFILES:
            try:
                results.append(audit_acc(page, prof))
                print("ACC", prof["tag"], results[-1].get("has_caveat_string"), results[-1].get("numbers_pct_found", [])[:3])
            except Exception as e:
                results.append({"tool": "acc_estimator_plus", "profile": prof["tag"], "status": "error", "error": str(e)})
            try:
                results.append(audit_aha_prevent_entry(page, prof))
                print("AHA/PREVENT", prof["tag"], results[-1].get("status"), results[-1].get("has_caveat_string"))
            except Exception as e:
                results.append({"tool": "aha_prevent", "profile": prof["tag"], "status": "error", "error": str(e)})
        browser.close()

    ok = [r for r in results if r.get("status") == "ok"]
    acc = [r for r in ok if r.get("tool") == "acc_estimator_plus"]
    aha = [r for r in ok if r.get("tool") == "aha_prevent"]
    report = {
        "timestamp_utc": ts,
        "n_runs": len(results),
        "n_ok": len(ok),
        "acc_n": len(acc),
        "aha_n": len(aha),
        "acc_caveat_positives": sum(1 for r in acc if r.get("has_caveat_string")),
        "acc_refuse_like": sum(1 for r in acc if r.get("appears_refused")),
        "aha_caveat_positives": sum(1 for r in aha if r.get("has_caveat_string")),
        "aha_refuse_like": sum(1 for r in aha if r.get("appears_refused")),
        "other_race_acc": next((r for r in acc if r.get("profile") == "other_race"), None),
        "oor_sbp_acc": next((r for r in acc if r.get("profile") == "oor_sbp"), None),
        "results": results,
        "note": "Official form-fill reference grid; compare caveat/refuse behavior to library oracles.",
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in report if k != "results"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
