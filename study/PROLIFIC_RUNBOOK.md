# Prolific runbook (Drift vignette study)

## Gate checklist (do not skip)
- [ ] IRB / ethics **exemption determination letter** on file (`IRB_EXEMPTION_REQUEST.md` drafted)
- [ ] OSF preregistration **timestamped** (`osf/preregistration.json`)
- [ ] Warranted-certainty keys dual-coded by two clinicians and locked
- [ ] Survey hosted on HTTPS with `/study/collect` reachable
- [ ] Completion code validation path tested end-to-end
- [ ] Debrief text reviewed

## Materials
- Survey UI: `study/prolific_survey.html` or Flask `/study/prolific`
- Collector: `POST /study/collect` → `study/results/responses.jsonl`
- Status: `GET /study/status`
- Analysis: `python scripts/analyze_study.py study/results/`
- Arms: two Prolific studies or URL balancer with `?arm=honest` / `?arm=baseline`
- **Do not** show arm name or researcher annotations to participants (survey already hardened)

## Suggested Prolific setup
- **Title:** Understanding health risk displays (academic study)
- **Device:** Desktop preferred
- **Time:** 10–12 minutes
- **Pay:** ≥ £9/hr equivalent (≈ £1.50–2.00 for 10–12 min)
- **Sample:** Pilot N=40 labeled pilot; then N≈600 analyzed (300/arm)
- **Screeners:** Age 18+; English fluent; optional race quotas (≥30% Black/Hispanic/Asian combined)
- **Attention:** built-in item; exclude failers per prereg
- **Completion code:** `DRIFT-XXXX` shown at end; match against collector JSONL

## Hosting
1. **Required:** `export SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')` — study assign refuses the default key.
2. `python scripts/render_study_fixtures.py && python app_v5.py` (port 5001)
3. HTTPS tunnel: `cloudflared tunnel --url http://127.0.0.1:5001`
4. Or deploy Flask behind any HTTPS reverse proxy
5. Static HTML alone cannot persist responses — use collector. Arms live in SQLite `study_assignments`, not the cookie.

## Analysis
Primary: calibrated overconfidence (stated − warranted) honest vs baseline.  
Secondary: comprehension; care-seeking on v6 (TOST).  
Export: `study/results/responses.jsonl` → `docs/facct/human_study_results.json`.
