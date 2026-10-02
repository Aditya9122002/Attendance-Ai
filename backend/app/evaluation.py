"""Scoring for the extraction eval set.

Purpose: measure how well a model extracts structured data from labelled parent replies.
Input: labelled cases (evals/*.jsonl) and the outcome the extractor produced for each.
Output: per-case results and a summary, including safety-relevant counts.
Dependencies: app.extraction only. No network access here; the CLI in scripts/ calls the model.

All replies in the dataset are made up. Never put real parent speech in this file.
"""

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any

from app.extraction import AbsenceReason, ExtractionOutcome

# Every case is evaluated as if today were this Friday, so "Monday" and "tomorrow" have
# fixed answers.
EVAL_TODAY = date(2026, 10, 2)


@dataclass(frozen=True)
class EvalCase:
    id: str
    reply: str
    reason: AbsenceReason
    expected_return_date: date | None
    needs_human_followup: bool
    tags: tuple[str, ...]


@dataclass(frozen=True)
class CaseResult:
    case: EvalCase
    outcome: ExtractionOutcome
    latency_ms: float

    @property
    def unavailable(self) -> bool:
        """The provider failed; this says nothing about model quality."""
        return self.outcome.error == "llm_unavailable"

    @property
    def reason_ok(self) -> bool:
        e = self.outcome.extraction
        return e is not None and e.reason == self.case.reason

    @property
    def date_ok(self) -> bool:
        e = self.outcome.extraction
        return e is not None and e.expected_return_date == self.case.expected_return_date

    @property
    def followup_ok(self) -> bool:
        e = self.outcome.extraction
        return e is not None and e.needs_human_followup == self.case.needs_human_followup

    @property
    def all_ok(self) -> bool:
        return self.reason_ok and self.date_ok and self.followup_ok

    @property
    def missed_emergency(self) -> bool:
        e = self.outcome.extraction
        return self.case.needs_human_followup and (e is None or not e.needs_human_followup)

    @property
    def false_alarm(self) -> bool:
        e = self.outcome.extraction
        return (not self.case.needs_human_followup) and e is not None and e.needs_human_followup


@dataclass(frozen=True)
class Summary:
    total: int
    scored: int
    unavailable: int
    invalid_output: int
    reason_accuracy: float | None
    date_accuracy: float | None
    followup_accuracy: float | None
    all_correct_rate: float | None
    missed_emergencies: int
    false_alarms: int
    median_latency_ms: float | None
    p95_latency_ms: float | None
    by_tag: dict[str, tuple[int, int]]  # tag -> (all correct, scored)


def load_cases(path: Path) -> list[EvalCase]:
    cases = []
    # Explicit UTF-8: Windows defaults to a legacy encoding that corrupts Hindi and Marathi.
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            raw: dict[str, Any] = json.loads(line)
            expected = raw["expected"]
            returns = expected["expected_return_date"]
            cases.append(
                EvalCase(
                    id=raw["id"],
                    reply=raw["reply"],
                    reason=AbsenceReason(expected["reason"]),
                    expected_return_date=date.fromisoformat(returns) if returns else None,
                    needs_human_followup=expected["needs_human_followup"],
                    tags=tuple(raw.get("tags", [])),
                )
            )
    return cases


def _ratio(count: int, total: int) -> float | None:
    return count / total if total else None


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile; None for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def summarize(results: list[CaseResult]) -> Summary:
    scored = [r for r in results if not r.unavailable]
    latencies = [r.latency_ms for r in results if not r.unavailable]
    by_tag: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in scored:
        for tag in r.case.tags:
            by_tag[tag][1] += 1
            by_tag[tag][0] += int(r.all_ok)
    return Summary(
        total=len(results),
        scored=len(scored),
        unavailable=len(results) - len(scored),
        invalid_output=sum(r.outcome.error == "invalid_output" for r in scored),
        reason_accuracy=_ratio(sum(r.reason_ok for r in scored), len(scored)),
        date_accuracy=_ratio(sum(r.date_ok for r in scored), len(scored)),
        followup_accuracy=_ratio(sum(r.followup_ok for r in scored), len(scored)),
        all_correct_rate=_ratio(sum(r.all_ok for r in scored), len(scored)),
        missed_emergencies=sum(r.missed_emergency for r in scored),
        false_alarms=sum(r.false_alarm for r in scored),
        median_latency_ms=median(latencies) if latencies else None,
        p95_latency_ms=percentile(latencies, 95),
        by_tag={tag: (c[0], c[1]) for tag, c in sorted(by_tag.items())},
    )


class OracleLlmClient:
    """Answers every case correctly. Used to prove the harness itself works (--dry-run)."""

    def __init__(self, cases: list[EvalCase]) -> None:
        self._cases = cases

    async def generate_json(self, *, system: str, user: str, schema: dict[str, Any]) -> str:
        for case in self._cases:
            if case.reply in user:
                return json.dumps(
                    {
                        "reason": case.reason.value,
                        "expected_return_date": (
                            case.expected_return_date.isoformat()
                            if case.expected_return_date
                            else None
                        ),
                        "needs_human_followup": case.needs_human_followup,
                        "confidence": 1.0,
                    }
                )
        raise AssertionError("OracleLlmClient does not know this reply")
