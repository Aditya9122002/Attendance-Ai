"""Run the intent-classifier eval set against a model and print a scorecard.

Examples (from the project root):
  uv run python scripts/eval_intents.py --dry-run
  uv run python scripts/eval_intents.py --model gemini-3.1-flash-lite

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
from app.intent_evaluation import (  # noqa: E402
    IntentResult,
    IntentSummary,
    OracleIntentClient,
    load_intent_cases,
    summarize_intents,
)
from app.llm.gemini import GeminiClient  # noqa: E402
from app.turn_analysis import INTENT_PROMPT_VERSION, classify_intent  # noqa: E402

DATASET = ROOT / "evals" / "turn_replies.jsonl"
RESULTS_DIR = ROOT / "evals" / "results"
UNAVAILABLE_RETRIES = 2


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def print_summary(model: str, s: IntentSummary) -> None:
    print(f"\n=== intents | {model} | prompt {INTENT_PROMPT_VERSION} ===")
    print(f"cases: {s.total}  scored: {s.scored}  provider-unavailable: {s.unavailable}")
    print(
        f"intent correct: {pct(s.intent_accuracy)}   has_question correct: "
        f"{pct(s.question_accuracy)}"
    )
    print(
        f"MISSED OVERRIDES: {s.missed_overrides}   FALSE UNLOCKS (identity): "
        f"{s.false_unlocks}   FALSE CONFIRMS: {s.false_confirms}   "
        f"false overrides: {s.false_overrides}"
    )
    if s.median_latency_ms is not None:
        print(f"latency: median {s.median_latency_ms:.0f} ms, p95 {s.p95_latency_ms:.0f} ms")
    print("by step (correct / scored):")
    for step, (ok, n) in s.by_step.items():
        print(f"  {step:<12} {ok}/{n}")
    if s.unavailable:
        print("\nSome calls failed at the provider (rate limit?). Re-run with a larger --delay.")


def print_failures(results: list[IntentResult]) -> None:
    failures = [r for r in results if not r.unavailable and not (r.intent_ok and r.question_ok)]
    if not failures:
        return
    print("\nFailures:")
    for r in failures:
        flags = []
        if r.missed_override:
            flags.append("MISSED OVERRIDE")
        if r.false_unlock:
            flags.append("FALSE UNLOCK")
        if r.false_confirm:
            flags.append("FALSE CONFIRM")
        if r.false_override:
            flags.append("false override")
        note = f"  [{', '.join(flags)}]" if flags else ""
        print(
            f"- {r.case.id} ({r.case.step.value}){note}\n    reply: {r.case.reply}\n"
            f"    want:  {r.case.intent.value} / question={r.case.has_question}\n"
            f"    got:   {r.predicted.value} / question={r.predicted_question}"
        )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="Gemini model id (default: GEMINI_MODEL setting)")
    parser.add_argument("--delay", type=float, default=4.0, help="seconds between calls")
    parser.add_argument("--limit", type=int, help="only run the first N cases")
    parser.add_argument("--dry-run", action="store_true", help="use a perfect fake model")
    args = parser.parse_args()

    cases = load_intent_cases(DATASET)[: args.limit]
    settings = get_settings()
    model = args.model or settings.gemini_model

    if args.dry_run:
        llm, model, delay = OracleIntentClient(cases), "dry-run (perfect fake model)", 0.0
    else:
        if settings.gemini_api_key is None:
            print("GEMINI_API_KEY is missing. Add it to .env or use --dry-run.")
            return 1
        llm, delay = GeminiClient(settings.gemini_api_key.get_secret_value(), model), args.delay

    results: list[IntentResult] = []
    for i, case in enumerate(cases, 1):
        for attempt in range(UNAVAILABLE_RETRIES + 1):
            started = time.perf_counter()
            classification, error = await classify_intent(llm, case.step, case.reply)
            latency = (time.perf_counter() - started) * 1000
            if error != "llm_unavailable" or attempt == UNAVAILABLE_RETRIES:
                break
            await asyncio.sleep(max(delay, 1.0) * 3)
        results.append(IntentResult(case, classification, error, latency))
        print(f"[{i}/{len(cases)}] {case.id}", flush=True)
        await asyncio.sleep(delay)

    summary = summarize_intents(results)
    print_summary(model, summary)
    print_failures(results)

    if not args.dry_run:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        out = RESULTS_DIR / f"intents-{model}-{INTENT_PROMPT_VERSION}-{stamp}.json"
        out.write_text(
            json.dumps(
                {
                    "kind": "intents",
                    "model": model,
                    "prompt_version": INTENT_PROMPT_VERSION,
                    "summary": summary.__dict__,
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
