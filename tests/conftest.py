import os

# Baseline arm is study-only; tests may exercise it.
os.environ.setdefault("STUDY_ALLOW_BASELINE", "1")
os.environ.setdefault("DRIFT_AUDIT", "0")
