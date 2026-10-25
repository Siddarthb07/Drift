# ML stack quarantine (FAccT framing)

The `ml/` package (`predictor.py`, `train_model.py`, synthetic NHANES-marginal generator) is **not on the serving path**.

Reasons it must not be cited as clinical evidence:

1. Labels are drawn from a logistic function of the same features (circular discrimination metrics).
2. Diabetes prevalence in `training_report.txt` is ~54.6% — not epidemiological.
3. Subgroup AUCs were previously null due to a scaled-feature sex mask bug.
4. `ml/safety.py` was documented as “implemented” while `app_v5.py` never called it.

Drift’s runtime accountability layer lives in `risk_engine.py` + `disclosure.py` + `claims.yaml`.

To train experimentally: `python -m ml.train_model` — outputs remain educational demos only.
