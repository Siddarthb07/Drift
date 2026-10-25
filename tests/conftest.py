import os
import sys
from pathlib import Path

# Repo root on sys.path (pytest 9+ importlib mode does not prepend it).
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Baseline arm is study-only; tests may exercise it.
os.environ.setdefault("STUDY_ALLOW_BASELINE", "1")
os.environ.setdefault("DRIFT_AUDIT", "0")
