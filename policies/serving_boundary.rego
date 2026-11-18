# Equivalent serving-boundary policy (enriched input).
# input.request = profile facts the serving layer reasonably has
# input.payload = object about to hit UI/API
# Encodes the same consumer disclosure requirements as Drift's ledger+public_view
# for fair baseline comparison — not Drift Python imports.
package drift.serving_boundary

default allow := false

pce_races := {"white", "aa"}
known_claims := {
	"prevent_ascvd", "pce_ascvd", "findrisc",
	"cancer_lifestyle", "cancer_lifestyle_factors", "health_age_heuristic",
	"bp_category_acc_aha", "bp_category_esc", "legacy_baseline",
}

# --- Wire shape (same as public_payload) ---
has_forbidden_exact if {
	walk(input.payload, [_, value])
	is_object(value)
	some k
	value[k]
	endswith(k, "_exact")
}

unknown_claim if {
	cid := input.payload.claim_id
	not cid in known_claims
}

has_hero if {
	v := input.payload.health_age
	v != null
}

has_hero if {
	v := input.payload.Cancer.relative_risk
	type_name(v) == "number"
}

interval_collapsed if {
	input.payload.Diabetes.score_range
	v := input.payload.Diabetes.risk_pct
	type_name(v) == "number"
	not input.payload.Diabetes.refused
}

# --- Request-aware refuse / routing (information baselines need) ---
missing_sbp_numeric if {
	not input.request.systolic
	cvd_numeric
}

under30_numeric if {
	input.request.age < 30
	cvd_numeric
}

over79_numeric if {
	input.request.age > 79
	cvd_numeric
}

unsupported_pce if {
	input.request.prefer_pce
	not input.request.race in pce_races
	eq := lower(input.payload.CVD.equation)
	eq == "pce"
	cvd_numeric
}

cvd_numeric if {
	v := input.payload.CVD.risk_pct
	type_name(v) == "number"
}

cvd_numeric if {
	input.payload.CVD.risk_pct_exact
}

cvd_numeric if {
	input.payload.CVD.risk_band_label
	not input.payload.CVD.refused
}

baseline_env_missing if {
	input.request.mode == "baseline"
	not input.request.study_allow_baseline
}

# --- Full-spec parity gates (B5): waist silent-default + SCORE2 invention ---
# Silent waist: point FINDRISC shown after defaulting missing waist (or flag set).
silent_waist_point if {
	input.payload.Diabetes.silent_waist_default == true
	v := input.payload.Diabetes.risk_pct
	type_name(v) == "number"
	not input.payload.Diabetes.refused
}

silent_waist_point if {
	not input.request.waist_cm
	v := input.payload.Diabetes.risk_pct
	type_name(v) == "number"
	not input.payload.Diabetes.refused
	not input.payload.Diabetes.score_range
}

# SCORE2 invention: regional path must not emit SCORE2 as equation or coefficients.
score2_invented if {
	eq := upper(input.payload.CVD.equation)
	contains(eq, "SCORE2")
}

score2_invented if {
	input.payload.CVD.score2_coefficients
}

# Nonbinary without sex_for_equation must not show numeric CVD.
nonbinary_sex_numeric if {
	lower(input.request.sex) == "nonbinary"
	not input.request.sex_for_equation
	cvd_numeric
}

allow if {
	not has_forbidden_exact
	not unknown_claim
	not has_hero
	not interval_collapsed
	not missing_sbp_numeric
	not under30_numeric
	not over79_numeric
	not unsupported_pce
	not baseline_env_missing
	not silent_waist_point
	not score2_invented
	not nonbinary_sex_numeric
}
