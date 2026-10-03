"""Scoring for the intent-classifier eval set.

Purpose: measure how well a model classifies what a parent said during a call.
Input: labelled cases (evals/turn_replies.jsonl) and the classification produced for each.
Output: per-case results and a summary that separates the safety-critical mistakes.
Dependencies: app.conversation, app.turn_analysis, app.evaluation (percentile). No network here.

All replies in the dataset are made up. Never put real parent speech in this file.

Mistakes are not equally bad, so they are counted separately:
- missed override: an opt-out, wrong number, request for a human, upset parent or call-later
  that was not recognised, so the call carries on when it should have stopped.
- false unlock: "yes" at the identity step when the parent did not confirm, which would
  reveal the child's name to the wrong person.
- false confirm: "yes" at the read-back when the parent did not agree, which would save an
  unconfirmed result.
- false override: a normal reply treated as an override. The call ends early; annoying, not unsafe.
"""

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

from app.conversation import Intent, Step
from app.evaluation import percentile
from app.turn_analysis import IntentClassification

OVERRIDE_INTENTS = frozenset(
    {Intent.OPT_OUT, Intent.WANTS_HUMAN, Intent.UPSET, Intent.WRONG_PERSON, Intent.CALL_LATER}
)


@dataclass(frozen=True)
class IntentCase:
    id: str
    step: Step
    reply: str
    intent: Intent
    has_question: bool
    tags: tuple[str, ...]


@dataclass(frozen=True)
class IntentResult:
    case: IntentCase
    classification: IntentClassification | None  # None when the output was unusable or unavailable
    error: str | None
    latency_ms: float

    @property
    def unavailable(self) -> bool:
        return self.error == "llm_unavailable"

    @property
    def predicted(self) -> Intent:
        # Unusable output is treated as UNCLEAR, exactly as the real pipeline does.
        return self.classification.intent if self.classification else Intent.UNCLEAR

    @property
    def predicted_question(self) -> bool:
        return self.classification.has_question if self.classification else False

    @property
    def intent_ok(self) -> bool:
        return self.predicted == self.case.intent

    @property
    def question_ok(self) -> bool:
        return self.predicted_question == self.case.has_question

    @property
    def missed_override(self) -> bool:
        return self.case.intent in OVERRIDE_INTENTS and self.predicted != self.case.intent

    @property
    def false_override(self) -> bool:
        return self.case.intent not in OVERRIDE_INTENTS and self.predicted in OVERRIDE_INTENTS

    @property
    def false_unlock(self) -> bool:
        return (
            self.case.step == Step.IDENTITY
            and self.predicted == Intent.YES
            and self.case.intent != Intent.YES
        )

    @property
    def false_confirm(self) -> bool:
        return (
            self.case.step == Step.CONFIRM
            and self.predicted == Intent.YES
            and self.case.intent != Intent.YES
        )


@dataclass(frozen=True)
class IntentSummary:
    total: int
    scored: int
    unavailable: int
    intent_accuracy: float | None
    question_accuracy: float | None
    missed_overrides: int
    false_overrides: int
    false_unlocks: int
    false_confirms: int
    median_latency_ms: float | None
    p95_latency_ms: float | None
    by_step: dict[str, tuple[int, int]]  # step -> (correct, scored)


def load_intent_cases(path: Path) -> list[IntentCase]:
    cases = []
    with path.open(encoding="utf-8") as f:  # explicit UTF-8: Windows defaults to a legacy encoding
        for line in f:
            if not line.strip():
                continue
            raw: dict[str, Any] = json.loads(line)
            cases.append(
                IntentCase(
                    id=raw["id"],
                    step=Step(raw["step"]),
                    reply=raw["reply"],
                    intent=Intent(raw["expected"]["intent"]),
                    has_question=raw["expected"]["has_question"],
                    tags=tuple(raw.get("tags", [])),
                )
            )
    return cases


def _ratio(count: int, total: int) -> float | None:
    return count / total if total else None


def summarize_intents(results: list[IntentResult]) -> IntentSummary:
    scored = [r for r in results if not r.unavailable]
    latencies = [r.latency_ms for r in scored]
    by_step: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in scored:
        by_step[r.case.step.value][1] += 1
        by_step[r.case.step.value][0] += int(r.intent_ok)
    return IntentSummary(
        total=len(results),
        scored=len(scored),
        unavailable=len(results) - len(scored),
        intent_accuracy=_ratio(sum(r.intent_ok for r in scored), len(scored)),
        question_accuracy=_ratio(sum(r.question_ok for r in scored), len(scored)),
        missed_overrides=sum(r.missed_override for r in scored),
        false_overrides=sum(r.false_override for r in scored),
        false_unlocks=sum(r.false_unlock for r in scored),
        false_confirms=sum(r.false_confirm for r in scored),
        median_latency_ms=median(latencies) if latencies else None,
        p95_latency_ms=percentile(latencies, 95),
        by_step={step: (c[0], c[1]) for step, c in sorted(by_step.items())},
    )


class OracleIntentClient:
    """Answers every case correctly. Used to prove the harness works (--dry-run)."""

    def __init__(self, cases: list[IntentCase]) -> None:
        self._cases = cases

    async def generate_json(self, *, system: str, user: str, schema: dict[str, Any]) -> str:
        # Match the reply exactly: one reply can be a substring of another ("Yes, speaking.").
        reply = user.split("<parent_reply>\n", 1)[1].rsplit("\n</parent_reply>", 1)[0]
        for case in self._cases:
            if case.reply == reply:
                return json.dumps({"intent": case.intent.value, "has_question": case.has_question})
        raise AssertionError("OracleIntentClient does not know this reply")
