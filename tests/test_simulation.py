import json
from datetime import date

import pytest

from app.call_service import StartResult
from app.conversation import Outcome
from app.extraction import PROMPT_VERSION, Extraction
from app.llm.base import LlmError
from app.llm.demo import KeywordDemoLlm
from app.llm.fake import ScriptedLlmClient
from app.simulation import run_simulation
from app.turn_analysis import IntentClassification

SUNDAY = date(2026, 10, 4)
INTENT_SCHEMA = IntentClassification.model_json_schema()
EXTRACTION_SCHEMA = Extraction.model_json_schema()


async def ask_intent(text: str) -> dict:
    user = f"The assistant asked something.\n<parent_reply>\n{text}\n</parent_reply>"
    raw = await KeywordDemoLlm().generate_json(system="", user=user, schema=INTENT_SCHEMA)
    return json.loads(raw)


async def ask_extraction(text: str, today: date = SUNDAY) -> dict:
    user = f"Today's date: {today.isoformat()}\n<parent_reply>\n{text}\n</parent_reply>"
    raw = await KeywordDemoLlm().generate_json(system="", user=user, schema=EXTRACTION_SCHEMA)
    return json.loads(raw)


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("Yes speaking", "yes"),
        ("haan ji", "yes"),
        ("No", "no"),
        ("Stop calling me", "opt_out"),
        ("I want to speak to the teacher", "wants_human"),
        ("this is stupid", "upset"),
        ("wrong number", "wrong_person"),
        ("I am busy, call later", "call_later"),
        ("He has fever", "answer"),
        ("No, he will be back on Monday", "answer"),
        ("hmm", "unclear"),
    ],
)
async def test_the_demo_model_understands_common_replies(text, intent):
    assert (await ask_intent(text))["intent"] == intent


async def test_the_demo_model_notices_a_question_it_cannot_answer():
    assert (await ask_intent("yes, what about the homework"))["has_question"] is True
    assert (await ask_intent("yes"))["has_question"] is False


async def test_the_demo_model_extracts_reason_and_return_date():
    result = await ask_extraction("He has fever, back on Monday")
    assert result["reason"] == "illness"
    assert result["expected_return_date"] == "2026-10-05"
    assert result["needs_human_followup"] is False


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("coming tomorrow", "2026-10-05"),
        ("day after tomorrow", "2026-10-06"),
        ("will return on 2026-10-09", "2026-10-09"),
        ("just fever", None),
    ],
)
async def test_the_demo_model_resolves_return_dates_from_the_given_today(text, expected):
    assert (await ask_extraction(text))["expected_return_date"] == expected


async def test_the_demo_model_names_the_same_weekday_a_week_ahead():
    result = await ask_extraction("back on Sunday")  # today is already a Sunday
    assert result["expected_return_date"] == "2026-10-11"


async def test_the_demo_model_flags_a_hospital_stay_for_a_person():
    result = await ask_extraction("he is in the hospital")
    assert result["reason"] == "other"
    assert result["needs_human_followup"] is True


async def test_the_demo_model_gives_no_reason_when_none_is_stated():
    assert (await ask_extraction("hmm"))["reason"] == "not_given"


async def test_the_demo_model_refuses_a_schema_it_does_not_know():
    with pytest.raises(LlmError):
        await KeywordDemoLlm().generate_json(
            system="", user="x\n<parent_reply>\nhi\n</parent_reply>", schema={"properties": {}}
        )


def replies(*texts: str):
    queue = iter(texts)
    return lambda: next(queue, None)


async def play(llm, *texts: str):
    said: list[str] = []
    report = await run_simulation(llm, replies(*texts), said.append, SUNDAY)
    return report, said


async def test_a_whole_simulated_call_completes_and_saves_the_result():
    report, said = await play(
        KeywordDemoLlm(),
        "Yes speaking",
        "He has fever, will be back on Monday",
        "Yes that is right",
    )

    assert report.start_result == StartResult.STARTED
    assert report.outcome == Outcome.COMPLETED
    assert report.event_status == "completed"
    assert report.reason == "illness"
    assert report.expected_return_date == date(2026, 10, 5)
    assert report.prompt_version == PROMPT_VERSION
    assert report.turns == 3
    assert report.attempt_number == 1
    assert report.dropped is False
    assert report.error is None
    assert len(said) == 4  # the opening line plus one answer per turn


async def test_the_simulated_opening_names_the_guardian_but_not_the_child():
    _, said = await play(KeywordDemoLlm())

    assert "Mr. Patil" in said[0]
    assert "Sunrise School" in said[0]
    assert "Asha" not in said[0]


async def test_a_simulated_opt_out_flags_the_guardian_and_asks_for_a_person():
    report, _ = await play(KeywordDemoLlm(), "Please stop calling me")

    assert report.outcome == Outcome.OPTED_OUT
    assert report.event_status == "needs_human"
    assert report.guardian_opted_out is True
    assert report.reason is None


async def test_a_parent_who_hangs_up_leaves_the_event_dialing():
    report, said = await play(KeywordDemoLlm())

    assert report.dropped is True
    assert report.outcome is None
    assert report.turns == 0
    assert report.event_status == "dialing"
    assert len(said) == 1


async def test_two_unclear_replies_end_the_call_and_queue_a_retry():
    report, _ = await play(KeywordDemoLlm(), "hmm", "hmm")

    assert report.outcome == Outcome.INCOMPLETE
    assert report.event_status == "pending"


async def test_a_model_outage_ends_the_simulated_call_politely():
    report, said = await play(ScriptedLlmClient(LlmError("down")), "Yes")

    assert report.outcome == Outcome.INCOMPLETE
    assert report.event_status == "pending"
    assert "technical problem" in said[-1]


@pytest.mark.parametrize(
    "text",
    ["She already left the home for school", "I don't know where he is", "woh school mein hai"],
)
async def test_the_demo_model_flags_a_child_whose_whereabouts_are_in_doubt(text):
    result = await ask_extraction(text)
    assert result["needs_human_followup"] is True
    assert result["reason"] == "not_given"


async def test_the_demo_model_does_not_flag_a_child_known_to_be_at_home():
    result = await ask_extraction("He is at home resting, he has fever")
    assert result["needs_human_followup"] is False
    assert result["reason"] == "illness"


async def test_a_parent_who_says_the_child_left_for_school_gets_a_person_not_a_retry():
    report, said = await play(KeywordDemoLlm(), "Yes speaking", "She already left the home")

    assert report.outcome == Outcome.ESCALATED
    assert report.event_status == "needs_human"
    assert report.needs_human_followup is True
    assert "letting the school know right away" in said[-1]
    assert "sorry to hear" not in said[-1]


async def test_a_parent_who_says_the_child_is_in_school_gets_a_person_not_a_retry():
    report, _ = await play(
        KeywordDemoLlm(),
        "Yes speaking",
        "He has fever, will be back on Monday",
        "No, he is not absent, he is in school",
    )

    assert report.outcome == Outcome.ESCALATED
    assert report.event_status == "needs_human"
