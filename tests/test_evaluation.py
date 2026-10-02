import json
import re
from pathlib import Path

from app.evaluation import (
    EVAL_TODAY,
    CaseResult,
    OracleLlmClient,
    load_cases,
    percentile,
    summarize,
)
from app.extraction import AbsenceReason, extract_absence_reply
from app.llm.base import LlmError
from app.llm.fake import ScriptedLlmClient

DATASET = Path(__file__).resolve().parents[1] / "evals" / "absence_replies.jsonl"
DEVANAGARI = re.compile(r"[\u0900-\u097F]")


async def run(client, cases):
    results = []
    for case in cases:
        outcome = await extract_absence_reply(client, case.reply, EVAL_TODAY)
        results.append(CaseResult(case=case, outcome=outcome, latency_ms=10.0))
    return results


def test_dataset_is_well_formed():
    cases = load_cases(DATASET)
    assert len(cases) >= 30
    assert len({c.id for c in cases}) == len(cases)
    assert {c.reason for c in cases} == set(AbsenceReason)
    assert all(
        c.expected_return_date is None or c.expected_return_date >= EVAL_TODAY for c in cases
    )
    tags = {t for c in cases for t in c.tags}
    assert {"en", "hi", "hinglish", "mr", "injection", "emergency"} <= tags


def test_hindi_and_marathi_survive_loading():
    cases = load_cases(DATASET)
    assert any(DEVANAGARI.search(c.reply) for c in cases if "hi" in c.tags)
    assert any(DEVANAGARI.search(c.reply) for c in cases if "mr" in c.tags)


async def test_a_perfect_model_scores_100_percent():
    cases = load_cases(DATASET)
    summary = summarize(await run(OracleLlmClient(cases), cases))
    assert summary.all_correct_rate == 1.0
    assert summary.missed_emergencies == 0
    assert summary.false_alarms == 0
    assert summary.unavailable == 0


async def test_a_lazy_model_misses_every_emergency():
    cases = load_cases(DATASET)
    lazy = json.dumps(
        {
            "reason": "not_given",
            "expected_return_date": None,
            "needs_human_followup": False,
            "confidence": 0.5,
        }
    )
    summary = summarize(await run(ScriptedLlmClient(*([lazy] * len(cases))), cases))
    assert summary.missed_emergencies == sum(c.needs_human_followup for c in cases)
    assert summary.false_alarms == 0
    assert summary.reason_accuracy < 0.3


async def test_provider_failures_are_excluded_from_accuracy_but_counted():
    cases = load_cases(DATASET)[:3]
    summary = summarize(await run(ScriptedLlmClient(*([LlmError("429")] * 3)), cases))
    assert summary.unavailable == 3
    assert summary.scored == 0
    assert summary.all_correct_rate is None


def test_percentile_uses_nearest_rank():
    values = [float(n) for n in range(1, 101)]
    assert percentile(values, 95) == 95.0
    assert percentile(values, 50) == 50.0
    assert percentile([], 95) is None
