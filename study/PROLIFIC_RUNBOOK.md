# Prolific runbook (Drift vignette study)

## Materials
- Survey UI: `study/prolific_survey.html` (static) or Flask route `/study/prolific`
- Protocol: `PROTOCOL.md`
- Items: `survey_items.md`
- Arms: `?arm=honest` or `?arm=baseline` (or random if omitted)

## Suggested Prolific setup
- **Title:** Understanding health risk displays (academic study)
- **Device:** Desktop preferred
- **Time:** 10 minutes
- **Pay:** Follow Prolific fair-pay (≥ £9/hr equivalent)
- **Sample:** N≈300 (150/arm); between-subjects
- **Screeners:** Age 18+; English fluent; optional oversample South Asian participants
- **Completion code:** Shown at end (`DRIFT-XXXX`); validate via downloaded JSON or hosted collector

## Hosting options
1. **Static:** Upload `prolific_survey.html` to any HTTPS host; set Prolific study URL with `?arm=honest` for half the slots and `?arm=baseline` for the other (two Prolific studies or URL balancer).
2. **Local/lab:** `python app_v5.py` → `http://127.0.0.1:5001/study/prolific`
3. **Collector (recommended before scale):** Add a small POST endpoint or use Qualtrics/Gorilla mirroring the same items; keep arm assignment server-side.

## IRB
Do not launch until IRB approval or exemption is on file. Vignettes are fictional; no participant health data in Drift `users.db`.

## Analysis
Primary: overconfidence (1–7) honest vs baseline (preregistered).  
Secondary: comprehension (% correct on MC keys `c`/`c`), care-seeking on high-risk vignette.  
Export: participant JSON downloads or aggregator CSV.
