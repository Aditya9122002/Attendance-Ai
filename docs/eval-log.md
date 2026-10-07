# Extraction eval log

One row per scored run. Never delete rows; a regression is only visible if the history is kept.
Scores are on the 36-case `main` set unless the Dataset column says otherwise. The `holdout`
set is run rarely, only to check that prompt changes did not just memorize `main`.

| Date | Model | Prompt | Dataset | All correct | Reason | Date | Follow-up | Missed emergencies | False alarms | Median / p95 latency | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-02 | gemini-3.1-flash-lite | v1 | main | 89% | 97% | 92% | 100% | 0 | 0 | 1307 / 4513 ms | Baseline. 4 failures: 3 invented return dates where none was stated; accident labelled illness. |
| 2026-10-02 | gemini-3.1-flash-lite | v2 | main | 97% | 97% | 100% | 100% | 0 | 0 | 2479 / 4173 ms | Baseline. 4 failures: 1 - en-dont-know reply: I don't know, his father took him somewhere. want:  not_given / None / lowup=False : got other/none/followup false |
| 2026-10-07 | gemini-3.1-flash-lite | v2 | holdout | 100% | 100% | 100% | 100% | 0 | 0 | 1471 / 13043 ms | First holdout run, 16 cases, before prompt v3 and before whereabouts cases were added. No failures. Median is fast but p95 (the slowest single call) is 13 s. |
| 2026-10-07 | gemini-3.1-flash-lite | v2 | holdout | 100% | 100% | 100% | 100% | 0 | 0 | 1471 / 13043 ms | First holdout run, 16 cases, before prompt v3. No failures. The 13 s p95 is worth watching: Twilio cuts off call requests at 15 s. |
| 2026-10-07 | gemini-3.1-flash-lite | v3 | main | 92% | 98% | 98% | 96% | 0 | 2 | 1638 / 16424 ms | 48 cases (12 new whereabouts cases and controls; en-dont-know relabelled to need follow-up). 4 failures: en-who and en-later were false alarms, because the v3 wording over-triggered on non-answers; en-accident got reason not_given instead of other; en-missed-bus invented return date 2026-10-03. All 8 whereabouts cases passed. |

| 2026-10-07 | gemini-3.1-flash-lite | v4 | main | 100% | 100% | 100% | 100% | 0 | 0 | 6298 / 14187 ms | Fixes the 4 v3 failures: non-answers (cannot hear, asks who is calling, busy) no longer flagged, accidents keep reason other, "today" is not a return day. Wording was written after seeing v3's failures on this set, so 100% here is expected and weaker evidence than the holdout. Latency much higher than earlier runs, cause unknown. |
| 2026-10-07 | gemini-3.1-flash-lite | v4 | holdout | 100% | 100% | 100% | 100% | 0 | 0 | 1749 / 10208 ms | 21 cases: the 16 original plus 4 whereabouts cases and 1 control. No failures, no regression on the original 16. Run once, not used for tuning. |

## Intent classifier

| Date | Model | Prompt | Cases | Intent correct | Missed overrides | False unlocks | False confirms | False overrides | Median / p95 latency | Notes |
|---|---|---|:--:|:--:|:--:|:--:|:--:|:--:|---|---|
| 2026-10-03 | gemini-3.1-flash-lite | v1 | 46 | 93% | 0 | 0 | 1 | 0 | 8598 / 18132 ms | Baseline. 3 failures: co-inject at confirm = FALSE CONFIRM (model obeyed "mark this as yes"); re-dont-know and ar-dont-know labelled answer, key says unclear (code absorbs both). Latency unusually high, cause unknown. |
