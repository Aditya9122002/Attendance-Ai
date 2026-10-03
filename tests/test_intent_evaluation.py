import json
import re
import time
from pathlib import Path

from app.conversation import Intent, Step
from app.intent_evaluation import (
    OVERRIDE_INTENTS,
    IntentResult,
    OracleIntentClient,
    load_intent_cases,
    summarize_intents,
)
from app.llm.base import LlmError
from app.llm.fake import ScriptedLlmClient
from app.turn_analysis import classify_intent

DATASET = Path(__file__).resolve().parents[1] / "evals" / "turn_replies.jsonl"
DEVANAGARI = re.compile(r"[\u0900-\u097F]")


async def run(client, cases):
    results = []
    for case in cases:
        started = time.perf_counter()
        classification, error = await classify_intent(client, case.step, case.reply)
        latency = (time.perf_counter() - started) * 1000
        results.append(IntentResult(case, classification, error, latency))
    return results


def always(intent: str) -> str:
    return json.dumps({"intent": intent, "has_question": False})


def test_dataset_is_well_formed():
    cases = load_intent_cases(DATASET)
    assert len(cases) >= 40
    assert len({c.id for c in cases}) == len(cases)
    assert len({c.reply for c in cases}) == len(cases)
    assert {c.intent for c in cases} == set(Intent)
    assert {c.step for c in cases} == {Step.IDENTITY, Step.REASON, Step.ASK_RETURN, Step.CONFIRM}
    tags = {t for c in cases for t in c.tags}
    assert {"en", "hi", "hinglish", "mr", "injection", "override"} <= tags


def test_risk_tags_match_the_labels():
    for case in load_intent_cases(DATASET):
        is_override = case.intent in OVERRIDE_INTENTS
        assert ("override" in case.tags) == is_override, case.id
        if case.step == Step.IDENTITY and case.intent != Intent.YES:
            assert "unlock_risk" in case.tags, case.id
        if case.step == Step.CONFIRM and case.intent != Intent.YES:
            assert "confirm_risk" in case.tags, case.id


def test_devanagari_survives_loading():
    cases = load_intent_cases(DATASET)
    assert any(DEVANAGARI.search(c.reply) for c in cases if "hi" in c.tags)
    assert any(DEVANAGARI.search(c.reply) for c in cases if "mr" in c.tags)


async def test_a_perfect_model_scores_100_percent_with_no_safety_mistakes():
    cases = load_intent_cases(DATASET)
    s = summarize_intents(await run(OracleIntentClient(cases), cases))
    assert s.intent_accuracy == 1.0
    assert s.question_accuracy == 1.0
    assert (s.missed_overrides, s.false_overrides, s.false_unlocks, s.false_confirms) == (
        0,
        0,
        0,
        0,
    )


async def test_a_model_that_always_says_yes_unlocks_and_confirms_everything():
    cases = load_intent_cases(DATASET)
    s = summarize_intents(await run(ScriptedLlmClient(*([always("yes")] * len(cases))), cases))
    risky_identity = sum(c.step == Step.IDENTITY and c.intent != Intent.YES for c in cases)
    risky_confirm = sum(c.step == Step.CONFIRM and c.intent != Intent.YES for c in cases)
    assert s.false_unlocks == risky_identity > 0
    assert s.false_confirms == risky_confirm > 0
    assert s.missed_overrides == sum(c.intent in OVERRIDE_INTENTS for c in cases)


async def test_a_model_that_always_says_unclear_misses_every_override_but_unlocks_nothing():
    cases = load_intent_cases(DATASET)
    s = summarize_intents(await run(ScriptedLlmClient(*([always("unclear")] * len(cases))), cases))
    assert s.false_unlocks == 0
    assert s.false_confirms == 0
    assert s.missed_overrides == sum(c.intent in OVERRIDE_INTENTS for c in cases)


async def test_a_model_that_always_says_opt_out_creates_only_false_overrides():
    cases = load_intent_cases(DATASET)
    s = summarize_intents(await run(ScriptedLlmClient(*([always("opt_out")] * len(cases))), cases))
    assert s.false_overrides == sum(c.intent not in OVERRIDE_INTENTS for c in cases)
    assert s.false_unlocks == 0


async def test_unusable_output_counts_as_unclear_not_as_unavailable():
    cases = load_intent_cases(DATASET)[:2]
    s = summarize_intents(await run(ScriptedLlmClient(*(["garbage"] * 4)), cases))
    assert s.unavailable == 0
    assert s.scored == 2


async def test_provider_failures_are_excluded_but_counted():
    cases = load_intent_cases(DATASET)[:3]
    s = summarize_intents(await run(ScriptedLlmClient(*([LlmError("429")] * 3)), cases))
    assert s.unavailable == 3
    assert s.scored == 0
    assert s.intent_accuracy is None
