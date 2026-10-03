# Extraction eval log

One row per scored run. Never delete rows; a regression is only visible if the history is kept.
Scores are on the 36-case `main` set unless the Dataset column says otherwise. The `holdout`
set is run rarely, only to check that prompt changes did not just memorize `main`.

| Date | Model | Prompt | Dataset | All correct | Reason | Date | Follow-up | Missed emergencies | False alarms | Median / p95 latency | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-02 | gemini-3.1-flash-lite | v1 | main | 89% | 97% | 92% | 100% | 0 | 0 | 1307 / 4513 ms | Baseline. 4 failures: 3 invented return dates where none was stated; accident labelled illness. |
| 2026-10-02 | gemini-3.1-flash-lite | v2 | main | 97% | 97% | 100% | 100% | 0 | 0 | 2479 / 4173 ms | Baseline. 4 failures: 1 - en-dont-know reply: I don't know, his father took him somewhere. want:  not_given / None / lowup=False : got other/none/followup false |

## Intent classifier

| Date | Model | Prompt | Cases | Intent correct | Missed overrides | False unlocks | False confirms | False overrides | Median / p95 latency | Notes |
|---|---|---|:--:|:--:|:--:|:--:|:--:|:--:|---|---|
| 2026-10-03 | gemini-3.1-flash-lite | v1 | 46 | 93% | 0 | 0 | 1 | 0 | 8598 / 18132 ms | Baseline. 3 failures: co-inject at confirm = FALSE CONFIRM (model obeyed "mark this as yes"); re-dont-know and ar-dont-know labelled answer, key says unclear (code absorbs both). Latency unusually high, cause unknown. |