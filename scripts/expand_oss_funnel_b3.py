#!/usr/bin/env python3
"""B3: Expand OSS funnel via GitHub search + record selection rules / exclusion codes."""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
OSS = ROOT / "docs" / "jbhi" / "outside_corpus" / "oss_checkout"
OUT = ROOT / "docs" / "jbhi" / "outside_corpus" / "funnel_b3.json"
OSS.mkdir(parents=True, exist_ok=True)

QUERIES = [
    "ascvd calculator language:Python",
    "ascvd calculator language:JavaScript",
    "pooled cohort equations language:Python",
    "prevent ascvd calculator language:Python",
    "framingham risk calculator language:JavaScript",
    "framingham risk score language:Python",
    "qrisk calculator language:Python",
    "ascvd risk language:TypeScript",
    "ascvd risk calculator language:Java",
    "framingham chd calculator language:Python",
    "cardiovascular risk calculator language:JavaScript",
    "prevent equations language:R",
    "aha prevent calculator",
    "acc aha ascvd language:Python",
    "pooled cohort ascvd language:JavaScript",
    "cvd risk score language:Go",
    "heart risk calculator language:TypeScript",
    "framingham risk language:C",
]

SELECTION_RULE = (
    "Include if README/code indicates a CVD/ASCVD/Framingham/PREVENT/QRISK calculator "
    "with extractable headless entry (library function, CLI, or pure JS). "
    "Exclude UI-only without formula, empty stubs, non-CVD, and service-bound FHIR/R without local engine. "
    "Primary analysis uses native runtime adapters; Docker is recorded for future parity, not required for inclusion."
)


def gh_search(q: str, page: int = 1) -> Dict[str, Any]:
    url = (
        "https://api.github.com/search/repositories?q="
        + urllib.parse.quote(q)
        + f"&per_page=30&page={page}"
    )
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "drift-jbhi-funnel",
        **({"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"} if os.environ.get("GITHUB_TOKEN") else {}),
    })
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode())


def clone_one(full: str, dest: Path) -> str:
    if dest.exists():
        return "already_cloned"
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", f"https://github.com/{full}.git", str(dest)],
            check=True, capture_output=True, timeout=120,
        )
        return "cloned"
    except Exception as e:
        return f"clone_fail:{type(e).__name__}"


def classify_local(name: str, path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"name": name, "code": "missing"}
    files = list(path.rglob("*"))
    code = [f for f in files if f.suffix.lower() in (".py", ".js", ".ts", ".r", ".c", ".java", ".go")]
    if not code:
        return {"name": name, "code": "no_calc_code", "reason": "no source files"}
    # Heuristic runnable
    has_py = any(f.suffix == ".py" for f in code)
    has_js = any(f.suffix in (".js", ".ts") for f in code)
    return {
        "name": name,
        "code": "has_code",
        "has_py": has_py,
        "has_js": has_js,
        "n_code_files": len(code),
    }


def main() -> int:
    discovered: Dict[str, Dict[str, Any]] = {}
    for q in QUERIES:
        for page in (1, 2):
            try:
                data = gh_search(q, page)
            except Exception as e:
                discovered.setdefault("_errors", {}).setdefault(q, str(e)[:200])
                break
            for item in data.get("items", []):
                full = item["full_name"]
                discovered[full] = {
                    "full_name": full,
                    "stars": item.get("stargazers_count"),
                    "language": item.get("language"),
                    "query": q,
                }
            time.sleep(1.2)  # be polite without token
            if data.get("total_count", 0) <= page * 30:
                break

    # Clone up to capacity (skip if already many)
    existing = {p.name for p in OSS.iterdir() if p.is_dir()}
    clone_log = []
    target_new = max(0, 120 - len(existing))
    n_new = 0
    for full, meta in sorted(discovered.items(), key=lambda kv: -(kv[1].get("stars") or 0)):
        if full.startswith("_"):
            continue
        if n_new >= min(target_new, 80):
            break
        dest_name = full.replace("/", "_")
        if dest_name in existing:
            continue
        status = clone_one(full, OSS / dest_name)
        clone_log.append({"repo": full, "status": status, "stars": meta.get("stars")})
        if status in ("cloned", "already_cloned"):
            n_new += 1
            existing.add(dest_name)
        time.sleep(0.3)

    # Classify all local checkouts
    local = []
    for p in sorted(OSS.iterdir()):
        if p.is_dir() and not p.name.startswith("."):
            local.append(classify_local(p.name, p))

    n_cloned = len(local)
    n_code = sum(1 for r in local if r.get("code") == "has_code")
    report = {
        "selection_rule": SELECTION_RULE,
        "github_discovered": len([k for k in discovered if not k.startswith("_")]),
        "cloned_total": n_cloned,
        "has_code_files": n_code,
        "clone_log": clone_log,
        "local_classification": local,
        "exclusion_reason_codes": [
            "no_calc_code", "ui_only_dom", "empty_clone", "service_bound_fhir_r",
            "mobile_android_java", "qrisk_incomplete", "clone_fail", "duplicate_fork",
        ],
        "note": "Runnable native adapters remain those with explicit harness entries; this script expands the clone set and documents the funnel.",
        "errors": discovered.get("_errors"),
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("github_discovered", "cloned_total", "has_code_files")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
