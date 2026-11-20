#!/usr/bin/env python3
"""B2: Downstream dependents of flagged libraries — caveat scan + popularity."""
from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "jbhi" / "outside_corpus" / "downstream_propagation.json"
CAVEAT_RE = re.compile(
    r"(other|white equation|caveat|not validated|under.?estimat|over.?estimat|"
    r"race.?free|apply.?white|may not apply|disclaimer|limitation)",
    re.I,
)

# Flagged PCE libraries from B1 (silent White, no machine-readable coverage signal)
FLAGGED = [
    {"repo": "Articulus-Tech/ascvd", "ecosystem": "pypi_or_github", "pypi": None, "npm": None},
    {"repo": "RonApplePAC/ascvd_calculator", "ecosystem": "npm_or_github", "pypi": None, "npm": None},
    {"repo": "sueinchoi/ascvd-calculator", "ecosystem": "npm_or_github", "pypi": None, "npm": None},
    {"repo": "abusuraihsakhri/ascvd-risk-calculator", "ecosystem": "github", "pypi": None, "npm": None},
]


def gh_api(url: str) -> Any:
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "drift-jbhi-audit",
        **({"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"} if os.environ.get("GITHUB_TOKEN") else {}),
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def repo_meta(full: str) -> Dict[str, Any]:
    try:
        d = gh_api(f"https://api.github.com/repos/{full}")
        return {"stars": d.get("stargazers_count"), "forks": d.get("forks_count"),
                "html_url": d.get("html_url"), "ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def dependents_approx(full: str) -> Dict[str, Any]:
    """Use GitHub code search / forks as mechanical proxy when dependency graph API unavailable."""
    out: Dict[str, Any] = {"forks_as_proxy": None, "network_count": None}
    try:
        d = gh_api(f"https://api.github.com/repos/{full}")
        out["forks_as_proxy"] = d.get("forks_count")
        out["stars"] = d.get("stargazers_count")
    except Exception as e:
        out["error"] = str(e)
    # Search for import-like references (rate-limited)
    try:
        import urllib.parse
        name = full.split("/")[-1]
        s = gh_api(f"https://api.github.com/search/code?q={urllib.parse.quote(name)}+in:file&per_page=5")
        out["code_search_total_count"] = s.get("total_count")
    except Exception as e:
        out["code_search_error"] = str(e)[:200]
    return out


def scan_local_checkout_for_ui_caveats() -> List[Dict[str, Any]]:
    """Scan OSS checkout apps that wrap flagged libraries for caveat strings in UI sources."""
    oss = ROOT / "docs" / "jbhi" / "outside_corpus" / "oss_checkout"
    rows = []
    # Known wrap relationships
    wraps = [
        ("babuljack_ascvdrisk", "Articulus-Tech_ascvd"),
        ("alinayu03_ASCVD-Risk", None),
        ("Fridsma_ASCVD_RiskCalculator", None),
        ("onedocfry_ASCVD-Risk-Calculatir", None),
        ("bbylw_ascvd-calculator", None),
        ("sueinchoi_ascvd-calculator", None),
        ("RonApplePAC_ascvd_calculator", None),
    ]
    for name, upstream in wraps:
        d = oss / name
        if not d.exists():
            continue
        texts = []
        for f in d.rglob("*"):
            if f.suffix.lower() in (".py", ".js", ".ts", ".tsx", ".html", ".vue", ".jsx", ".md"):
                if f.stat().st_size > 500_000:
                    continue
                try:
                    texts.append(f.read_text(errors="ignore"))
                except Exception:
                    pass
        blob = "\n".join(texts)
        has = bool(CAVEAT_RE.search(blob))
        # machine-readable: look for caveat fields in return objects
        machine = bool(re.search(r"caveat|coverage_note|disclaimer_field|race_note", blob, re.I))
        rows.append({
            "downstream_or_surface": name,
            "upstream_flagged": upstream,
            "ui_or_source_has_caveat_string": has,
            "machine_readable_coverage_field": machine,
            "adds_no_machine_readable_caveat": not machine,
        })
    return rows


def main() -> int:
    import urllib.parse  # noqa: F401
    local = scan_local_checkout_for_ui_caveats()
    n = len(local)
    m = sum(1 for r in local if r["adds_no_machine_readable_caveat"])
    remote = []
    for f in FLAGGED:
        meta = repo_meta(f["repo"])
        dep = dependents_approx(f["repo"]) if meta.get("ok") else {}
        remote.append({**f, "meta": meta, "dependents": dep})

    total_stars = sum((r.get("meta") or {}).get("stars") or 0 for r in remote)
    report = {
        "flagged_libraries": FLAGGED,
        "local_surface_scan": local,
        "local_summary": {
            "n_surfaces": n,
            "n_without_machine_readable_caveat": m,
            "pct_without_machine_readable_caveat": (m / n) if n else None,
            "sentence": (
                f"Among {n} local downstream/app surfaces of flagged PCE calculators, "
                f"{m}/{n} ({(m/n if n else 0):.0%}) add no machine-readable coverage caveat field."
            ),
        },
        "remote_github": remote,
        "remote_stars_sum": total_stars,
        "note": (
            "GitHub Dependency Graph / npm dependents require auth for full counts; "
            "forks+code-search and local UI scans are the mechanical evidence shipped here."
        ),
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["local_summary"], indent=2))
    print("remote_stars_sum", total_stars)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
