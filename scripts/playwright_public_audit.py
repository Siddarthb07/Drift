#!/usr/bin/env python3
"""A1/A3: Playwright public-tool + official calculator audit (mechanical).

Drives each tool URL with a fixed profile, extracts rendered text, runs caveat
regex + numeric extraction, saves DOM snapshot + screenshot with SHA-256.
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
OUT_DIR = ROOT / "docs" / "jbhi" / "outside_corpus" / "playwright_audit"
OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT = ROOT / "docs" / "jbhi" / "outside_corpus" / "playwright_audit_report.json"

CAVEAT_RE = re.compile(
    r"(other|white equation|caveat|not validated|under.?estimat|over.?estimat|"
    r"race.?free|apply.?white|may not apply|disclaimer|limitation|coverage)",
    re.I,
)
NUM_RE = re.compile(r"(\d{1,2}(?:\.\d+)?)\s*%")

# Expandable catalog — official first (A3), then public tools (A1 target ≥40)
TOOLS: List[Dict[str, Any]] = [
    {"id": "acc_estimator_plus", "role": "official", "url": "https://tools.acc.org/ASCVD-Risk-Estimator-Plus/#!/calculate/estimate/",
     "notes": "ACC Risk Estimator Plus — reference standard"},
    {"id": "aha_prevent", "role": "official", "url": "https://professional.heart.org/en/guidelines-and-statements/prevent-calculator",
     "notes": "AHA PREVENT entry — may redirect"},
    {"id": "clincalc_prevent", "role": "professional", "url": "https://clincalc.com/Cardiology/ASCVD/PREVENT.aspx"},
    {"id": "mdcalc_ascvd", "role": "professional", "url": "https://www.mdcalc.com/calc/3394/ascvd-atherosclerotic-cardiovascular-disease-2013-risk-calculator-aha-acc"},
    {"id": "qrisk3", "role": "professional", "url": "https://qrisk.org/three/"},
    {"id": "framingham_hp2013", "role": "professional", "url": "https://www.framinghamheartstudy.org/fhs-risk-functions/cardiovascular-disease-10-year-risk/"},
    {"id": "omnicalculator_ascvd", "role": "consumer", "url": "https://www.omnicalculator.com/health/ascvd"},
    {"id": "calculator_net_heart", "role": "consumer", "url": "https://www.calculator.net/heart-disease-risk-calculator.html"},
    {"id": "medscape_ascvd", "role": "professional", "url": "https://reference.medscape.com/calculator/ascvd-atherosclerotic-cvd-risk-aha"},
    {"id": "mayoclinic_heart", "role": "consumer", "url": "https://www.mayoclinic.org/diseases-conditions/heart-disease/in-depth/heart-disease-risk/art-20044547"},
    {"id": "webmd_heart_risk", "role": "consumer", "url": "https://www.webmd.com/heart-disease/heart-disease-risk-factors"},
    {"id": "healthline_ascvd", "role": "consumer", "url": "https://www.healthline.com/health/heart-disease/ascvd"},
    {"id": "verywell_ascvd", "role": "consumer", "url": "https://www.verywellhealth.com/ascvd-risk-calculator-5216048"},
    {"id": "cardiosmart_risk", "role": "consumer", "url": "https://www.cardiosmart.org/topics/high-cholesterol/know-your-risk"},
    {"id": "stanford_prevent", "role": "professional", "url": "https://med.stanford.edu/content/sm/cerc/research/prevent.html"},
    {"id": "uptodate_cvd", "role": "professional", "url": "https://www.uptodate.com/contents/calculator-cardiovascular-risk-assessment-10-year-acc-aha-2013"},
    {"id": "esc_heartscore", "role": "professional", "url": "https://www.heartscore.org/en_GB/"},
    {"id": "who_cvd", "role": "professional", "url": "https://www.who.int/news-room/questions-and-answers/item/cardiovascular-disease-(cvds)"},
    {"id": "cdc_heart", "role": "consumer", "url": "https://www.cdc.gov/heart-disease/risk-factors/index.html"},
    {"id": "nih_heart_truth", "role": "consumer", "url": "https://www.nhlbi.nih.gov/health/heart-truth"},
    {"id": "aha_risk_factors", "role": "consumer", "url": "https://www.heart.org/en/health-topics/heart-attack/understand-your-risks-to-prevent-a-heart-attack"},
    {"id": "acc_patient", "role": "consumer", "url": "https://www.cardiosmart.org/"},
    {"id": "myhealth_alberta", "role": "consumer", "url": "https://myhealth.alberta.ca/Health/Pages/conditions.aspx?hwid=zp3381"},
    {"id": "bhf_risk", "role": "consumer", "url": "https://www.bhf.org.uk/informationsupport/risk-factors"},
    {"id": "nhs_cvd", "role": "consumer", "url": "https://www.nhs.uk/conditions/cardiovascular-disease/"},
    {"id": "inside_tracker", "role": "bioage", "url": "https://www.insidetracker.com/"},
    {"id": "everlywell", "role": "bioage", "url": "https://www.everlywell.com/"},
    {"id": "function_health", "role": "bioage", "url": "https://www.functionhealth.com/"},
    {"id": "superpower", "role": "bioage", "url": "https://www.superpower.com/"},
    {"id": "levels_health", "role": "bioage", "url": "https://www.levelshealth.com/"},
    {"id": "whoop", "role": "bioage", "url": "https://www.whoop.com/"},
    {"id": "oura", "role": "bioage", "url": "https://ouraring.com/"},
    {"id": "fitbit_health", "role": "bioage", "url": "https://www.fitbit.com/global/us/technology/health-metrics"},
    {"id": "apple_heart", "role": "bioage", "url": "https://www.apple.com/ios/health/"},
    {"id": "garmin_health", "role": "bioage", "url": "https://www.garmin.com/en-US/health/"},
    {"id": "withings", "role": "bioage", "url": "https://www.withings.com/"},
    {"id": "thrive_global", "role": "wellness", "url": "https://thriveglobal.com/"},
    {"id": "noom", "role": "wellness", "url": "https://www.noom.com/"},
    {"id": "weightwatchers", "role": "wellness", "url": "https://www.weightwatchers.com/"},
    {"id": "virgin_pulse", "role": "wellness", "url": "https://www.virginpulse.com/"},

]

# Fixed probe profile (Goff worked example white female + Other-race twin)
PROFILES = [
    {"tag": "pce_wf", "age": 55, "sex": "female", "race": "white", "tc": 213, "hdl": 50, "sbp": 120},
    {"tag": "other_race", "age": 55, "sex": "female", "race": "other", "tc": 213, "hdl": 50, "sbp": 120},
]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def extract_oracles(text: str) -> Dict[str, Any]:
    nums = [float(x) for x in NUM_RE.findall(text)]
    return {
        "has_caveat_string": bool(CAVEAT_RE.search(text)),
        "numbers_pct_found": nums[:20],
        "text_len": len(text),
    }


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        REPORT.write_text(json.dumps({
            "error": "playwright not installed",
            "fix": "pip install playwright && playwright install chromium",
            "catalog_n": len(TOOLS),
        }, indent=2))
        print("NEED_PLAYWRIGHT")
        return 2

    results = []
    ts = datetime.now(timezone.utc).isoformat()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        for tool in TOOLS:
            row: Dict[str, Any] = {"id": tool["id"], "role": tool["role"], "url": tool["url"], "ts": ts}
            try:
                page.goto(tool["url"], wait_until="domcontentloaded", timeout=60000)
                time.sleep(2.5)
                text = page.inner_text("body")
                snap = OUT_DIR / f"{tool['id']}.dom.html"
                shot = OUT_DIR / f"{tool['id']}.png"
                snap.write_text(page.content())
                page.screenshot(path=str(shot), full_page=True)
                row["oracles"] = extract_oracles(text)
                row["dom_sha256"] = sha256_file(snap)
                row["png_sha256"] = sha256_file(shot)
                row["status"] = "ok"
                # Official reference notes
                if tool["role"] == "official":
                    row["reference_standard"] = True
                    row["disclosure_ok_if"] = "Other-race path shows caveat string OR refuses unsupported stratum"
            except Exception as e:
                row["status"] = "error"
                row["error"] = f"{type(e).__name__}: {e}"
            results.append(row)
            print(tool["id"], row.get("status"), row.get("oracles", {}).get("has_caveat_string"))
        browser.close()

    n_ok = sum(1 for r in results if r.get("status") == "ok")
    report = {
        "timestamp_utc": ts,
        "n_tools_attempted": len(TOOLS),
        "n_ok": n_ok,
        "official_ids": [t["id"] for t in TOOLS if t["role"] == "official"],
        "results": results,
        "profiles_planned": PROFILES,
        "note": "Initial crawl captures landing/estimator pages; form-fill adapters expand per-tool next.",
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("n_tools_attempted", "n_ok", "official_ids")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
