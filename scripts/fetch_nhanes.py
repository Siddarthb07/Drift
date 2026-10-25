#!/usr/bin/env python3
"""Download NHANES 2017–2020 XPTs used by the coverage audit (with size checks)."""
from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "nhanes"
BASE = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles"
FILES = [
    "P_DEMO", "P_BPXO", "P_BMX", "P_HDL", "P_TCHOL", "P_BIOPRO",
    "P_SMQ", "P_DIQ", "P_BPQ", "P_GHB",
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name in FILES:
        dest = OUT / f"{name}.xpt"
        url = f"{BASE}/{name}.xpt"
        if dest.exists() and dest.stat().st_size > 50_000:
            print("HAVE", name, dest.stat().st_size)
        else:
            print("GET", url)
            urllib.request.urlretrieve(url, dest)
        h = hashlib.sha256(dest.read_bytes()).hexdigest()
        manifest[name] = {"bytes": dest.stat().st_size, "sha256": h}
    (OUT / "MANIFEST.sha256.json").write_text(
        __import__("json").dumps(manifest, indent=2), encoding="utf-8"
    )
    print("Wrote", OUT / "MANIFEST.sha256.json")


if __name__ == "__main__":
    main()
