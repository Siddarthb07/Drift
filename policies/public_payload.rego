# Drift public-payload disclosure policy (OPA / Rego).
# Evaluated against simulated public API/template objects — not engine audit objects.
package drift.public_payload

default allow := false

# Exact percents and nested audit exacts are forbidden on the public wire.
has_forbidden_exact if {
	walk(input, [path, value])
	is_object(value)
	some k
	value[k]
	endswith(k, "_exact")
}

# Unknown claim IDs fail closed when claim_id is present.
unknown_claim if {
	input.claim_id
	not input.claim_id in {
		"prevent_ascvd", "pce_ascvd", "findrisc",
		"cancer_lifestyle", "health_age_heuristic",
		"bp_category_acc_aha", "bp_category_esc",
	}
}

# Hero fields prohibited on consumer public payloads (null counts as absent).
has_hero if {
	v := input.health_age
	v != null
}

has_hero if {
	v := input.Cancer.relative_risk
	type_name(v) == "number"
}

has_hero if {
	v := input.CVD.relative_risk_exact
	v != null
}

# Interval must not collapse to a point percent when score_range is declared.
interval_collapsed if {
	input.Diabetes.score_range
	v := input.Diabetes.risk_pct
	type_name(v) == "number"
	not input.Diabetes.refused
}

allow if {
	not has_forbidden_exact
	not unknown_claim
	not has_hero
	not interval_collapsed
}

violations[msg] if {
	has_forbidden_exact
	msg := "forbidden_*_exact_on_public_payload"
}

violations[msg] if {
	unknown_claim
	msg := "unknown_claim_id"
}

violations[msg] if {
	has_hero
	msg := "prohibited_hero_field"
}

violations[msg] if {
	interval_collapsed
	msg := "interval_collapsed_to_point"
}
