"""Play one phone call in the terminal: you type what the parent says.

Examples (from the project root):
  uv run python scripts/simulate_call.py --fake
  uv run python scripts/simulate_call.py --model gemini-3.1-flash-lite

--fake uses a crude keyword stand-in for the model (no network, no key). Without it the real
Gemini model is used and GEMINI_API_KEY must be in .env. Uses made-up data in a throwaway
in-memory database. Type your replies at the PARENT> prompt; press Ctrl+C or Ctrl+Z then
Enter (Windows) to hang up.
"""

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.llm.demo import KeywordDemoLlm  # noqa: E402
from app.llm.gemini import GeminiClient  # noqa: E402
from app.simulation import SimulationReport, run_simulation  # noqa: E402


def read_reply() -> str | None:
    try:
        return input("PARENT> ")
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def say(line: str) -> None:
    print(f"ASSISTANT> {line}\n")


def print_report(report: SimulationReport) -> None:
    print("=== call finished ===")
    print(f"start result:        {report.start_result.value}")
    print(f"turns:               {report.turns}")
    print(f"outcome:             {report.outcome.value if report.outcome else 'none'}")
    print(f"event status:        {report.event_status}")
    print(f"saved reason:        {report.reason}")
    print(f"saved return date:   {report.expected_return_date}")
    print(f"needs human followup: {report.needs_human_followup}")
    print(f"prompt version:      {report.prompt_version}")
    print(f"guardian opted out:  {report.guardian_opted_out}")
    if report.dropped:
        print("The parent hung up before the call finished (the event stays 'dialing').")
    if report.error:
        print(f"Stopped on an error: {report.error}")
    print("Nothing was stored except the fields above: the conversation itself is not saved.")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fake", action="store_true", help="use the keyword stand-in model")
    parser.add_argument("--model", help="Gemini model id (default: GEMINI_MODEL setting)")
    parser.add_argument("--today", help="pretend today is YYYY-MM-DD (default: the real date)")
    args = parser.parse_args()

    today = date.fromisoformat(args.today) if args.today else date.today()
    settings = get_settings()
    if args.fake:
        llm = KeywordDemoLlm()
    else:
        if settings.gemini_api_key is None:
            print("GEMINI_API_KEY is missing. Add it to .env or use --fake.")
            return 1
        llm = GeminiClient(
            settings.gemini_api_key.get_secret_value(), args.model or settings.gemini_model
        )

    print(f"Pretend today is {today:%A, %d %B %Y}. You are the parent. Made-up data only.\n")
    report = await run_simulation(llm, read_reply, say, today)
    print_report(report)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(asyncio.run(main()))
