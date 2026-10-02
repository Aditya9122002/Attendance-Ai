"""Run the extraction eval set against a model and print a scorecard.

Examples (from the project root):
  uv run python scripts/eval_extraction.py --dry-run
  uv run python scripts/eval_extraction.py --model gemini-3.1-flash-lite
  uv run python scripts/eval_extraction.py --model gemini-3.5-flash-lite --delay 6

Uses made-up replies only. Needs GEMINI_API_KEY in .env unless --dry-run.
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.evaluation import (  # noqa: E402
    EVAL_TODAY,
    CaseResult,
    OracleLlmClient,
    Summary,
    load_cases,
    summarize,
)
from app.extraction import extract_absence_reply  # noqa: E402
from app.llm.gemini import GeminiClient  # noqa: E402

DATASET = ROOT / "evals" / "absence_replies.jsonl"
RESULTS_DIR = ROOT / "evals" / "results"
UNAVAILABLE_RETRIES = 2


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def print_summary(model: str, s: Summary) -> None:
    print(f"\n=== {model} ===")
    print(f"cases: {s.total}  scored: {s.scored}  provider-unavailable: {s.unavailable}")
    print(f"all fields correct: {pct(s.all_correct_rate)}")
    print(
        f"  reason: {pct(s.reason_accuracy)}   return date: {pct(s.date_accuracy)}   "
        f"follow-up flag: {pct(s.followup_accuracy)}"
    )
    print(
        f"MISSED EMERGENCIES: {s.missed_emergencies}   false alarms: {s.false_alarms}   "
        f"invalid outputs: {s.invalid_output}"
    )
    if s.median_latency_ms is not None:
        print(f"latency: median {s.median_latency_ms:.0f} ms, p95 {s.p95_latency_ms:.0f} ms")
    print("by tag (all-correct / scored):")
    for tag, (ok, n) in s.by_tag.items():
        print(f"  {tag:<14} {ok}/{n}")
    if s.unavailable:
        print("\nSome calls failed at the provider (rate limit?). Re-run with a larger --delay.")


def print_failures(results: list[CaseResult]) -> None:
    failures = [r for r in results if not r.unavailable and not r.all_ok]
    if not failures:
        return
    print("\nFailures:")
    for r in failures:
        e = r.outcome.extraction
        got = (
            f"{e.reason.value} / {e.expected_return_date} / followup={e.needs_human_followup}"
            if e
            else f"no result ({r.outcome.error})"
        )
        want = (
            f"{r.case.reason.value} / {r.case.expected_return_date} / "
            f"followup={r.case.needs_human_followup}"
        )
        print(f"- {r.case.id}\n    reply: {r.case.reply}\n    want:  {want}\n    got:   {got}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="Gemini model id (default: GEMINI_MODEL setting)")
    parser.add_argument("--delay", type=float, default=4.0, help="seconds between calls")
    parser.add_argument("--limit", type=int, help="only run the first N cases")
    parser.add_argument("--dry-run", action="store_true", help="use a perfect fake model")
    args = parser.parse_args()

    cases = load_cases(DATASET)[: args.limit]
    settings = get_settings()
    model = args.model or settings.gemini_model

    if args.dry_run:
        llm, model, delay = OracleLlmClient(cases), "dry-run (perfect fake model)", 0.0
    else:
        if settings.gemini_api_key is None:
            print("GEMINI_API_KEY is missing. Add it to .env or use --dry-run.")
            return 1
        llm, delay = GeminiClient(settings.gemini_api_key.get_secret_value(), model), args.delay

    results: list[CaseResult] = []
    for i, case in enumerate(cases, 1):
        for attempt in range(UNAVAILABLE_RETRIES + 1):
            started = time.perf_counter()
            outcome = await extract_absence_reply(llm, case.reply, EVAL_TODAY)
            latency = (time.perf_counter() - started) * 1000
            if outcome.error != "llm_unavailable" or attempt == UNAVAILABLE_RETRIES:
                break
            await asyncio.sleep(max(delay, 1.0) * 3)
        results.append(CaseResult(case=case, outcome=outcome, latency_ms=latency))
        print(f"[{i}/{len(cases)}] {case.id}", flush=True)
        await asyncio.sleep(delay)

    summary = summarize(results)
    print_summary(model, summary)
    print_failures(results)

    if not args.dry_run:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        out = RESULTS_DIR / f"{model}-{stamp}.json"
        out.write_text(
            json.dumps(
                {
                    "model": model,
                    "summary": summary.__dict__,
                    "cases": [
                        {
                            "id": r.case.id,
                            "ok": r.all_ok,
                            "error": r.outcome.error,
                            "latency_ms": round(r.latency_ms),
                        }
                        for r in results
                    ],
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        print(f"\nSaved: {out}")
    return 0


if __name__ == "__main__":
    # Hindi and Marathi replies must print on a Windows console without crashing.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(asyncio.run(main()))
