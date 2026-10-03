import itertools
from datetime import date

import pytest

from app.conversation import (
    PHRASES,
    Analysis,
    CallContext,
    ConversationState,
    Escalation,
    Intent,
    Outcome,
    Step,
    decide,
    end_for_technical_problem,
    opening,
    result_to_store,
)
from app.extraction import AbsenceReason, Extraction

CTX = CallContext(school_name="Sunrise School", guardian_name="Mr Patil", student_name="Asha")
MONDAY = date(2026, 10, 5)


def extraction(
    reason=AbsenceReason.ILLNESS, returns=MONDAY, followup=False, confidence=0.9
) -> Extraction:
    return Extraction(
        reason=reason,
        expected_return_date=returns,
        needs_human_followup=followup,
        confidence=confidence,
    )


def answer(**kwargs) -> Analysis:
    return Analysis(Intent.ANSWER, extraction(**kwargs))


def say(intent: Intent) -> Analysis:
    return Analysis(intent)


def state_at(step: Step, **kwargs) -> ConversationState:
    if step in (Step.CONFIRM, Step.ASK_RETURN) and "extraction" not in kwargs:
        kwargs["extraction"] = extraction()
    return ConversationState(step=step, **kwargs)


def run(analyses: list[Analysis], state: ConversationState | None = None):
    state = state or ConversationState()
    spoken = []
    for analysis in analyses:
        result = decide(state, analysis, CTX)
        state = result.state
        spoken.append(result.say)
    return state, spoken


# ---- happy paths -----------------------------------------------------------------------


def test_happy_path_with_a_return_date():
    state, spoken = run([say(Intent.YES), answer(), say(Intent.YES)])
    assert state.step == Step.ENDED
    assert state.outcome == Outcome.COMPLETED
    assert "Monday, 5 October" in spoken[1]
    assert result_to_store(state).reason == AbsenceReason.ILLNESS


def test_missing_return_date_is_asked_for_exactly_once():
    state, spoken = run([say(Intent.YES), answer(returns=None)])
    assert state.step == Step.ASK_RETURN
    assert "When do you expect Asha to return" in spoken[1]
    # Still no date: move on to the read-back, do not ask again.
    state, spoken = run([Analysis(Intent.UNCLEAR)], state)
    assert state.step == Step.CONFIRM
    assert "and will return" not in spoken[0]


def test_a_date_given_on_its_own_is_merged_with_the_earlier_reason():
    state, _ = run(
        [
            say(Intent.YES),
            answer(returns=None),
            answer(reason=AbsenceReason.NOT_GIVEN, returns=MONDAY),
        ]
    )
    assert state.step == Step.CONFIRM
    assert state.extraction.reason == AbsenceReason.ILLNESS
    assert state.extraction.expected_return_date == MONDAY


# ---- privacy: nothing about the child before the caller is confirmed --------------------


def test_opening_names_school_and_guardian_but_not_the_child():
    text = opening(CTX)
    assert "Sunrise School" in text
    assert "Mr Patil" in text
    assert "automated" in text  # the agent says it is not a person
    assert "Asha" not in text


@pytest.mark.parametrize("intent", list(Intent))
@pytest.mark.parametrize("with_extraction", [False, True])
@pytest.mark.parametrize("has_question", [False, True])
def test_no_line_before_confirmation_contains_the_childs_name(
    intent, with_extraction, has_question
):
    analysis = Analysis(intent, extraction() if with_extraction else None, has_question)
    result = decide(ConversationState(), analysis, CTX)
    if result.state.step != Step.REASON:  # REASON means identity was confirmed
        assert "Asha" not in result.say


def test_an_informative_reply_does_not_unlock_the_childs_details():
    result = decide(ConversationState(), answer(), CTX)
    assert result.state.step == Step.IDENTITY
    assert "Asha" not in result.say


def test_every_phrase_that_can_be_spoken_before_confirmation_has_no_child_name():
    pre_confirmation = [
        "opening",
        "identity_retry",
        "close_wrong_person",
        "close_opt_out",
        "close_call_later",
        "close_escalated",
        "close_emergency",
        "close_incomplete",
        "close_technical",
        "question_prefix",
    ]
    for key in pre_confirmation:
        assert "{student}" not in PHRASES["en"][key], key


# ---- identity step ---------------------------------------------------------------------


def test_saying_no_at_identity_ends_as_wrong_person():
    state, spoken = run([say(Intent.NO)])
    assert state.outcome == Outcome.WRONG_PERSON
    assert "Asha" not in spoken[0]


def test_two_unclear_replies_at_identity_end_incomplete():
    state, spoken = run([say(Intent.UNCLEAR), say(Intent.UNCLEAR)])
    assert state.outcome == Outcome.INCOMPLETE
    assert all("Asha" not in line for line in spoken)


# ---- rules that win in every step ------------------------------------------------------

ACTIVE_STEPS = [Step.IDENTITY, Step.REASON, Step.ASK_RETURN, Step.CONFIRM]


@pytest.mark.parametrize("step", ACTIVE_STEPS)
@pytest.mark.parametrize(
    ("intent", "outcome", "escalation"),
    [
        (Intent.OPT_OUT, Outcome.OPTED_OUT, None),
        (Intent.WRONG_PERSON, Outcome.WRONG_PERSON, None),
        (Intent.CALL_LATER, Outcome.CALL_LATER, None),
        (Intent.WANTS_HUMAN, Outcome.ESCALATED, Escalation.WANTS_HUMAN),
        (Intent.UPSET, Outcome.ESCALATED, Escalation.UPSET),
    ],
)
def test_overrides_win_in_every_step(step, intent, outcome, escalation):
    result = decide(state_at(step), say(intent), CTX)
    assert result.ended
    assert result.state.outcome == outcome
    assert result.state.escalation == escalation
    assert result_to_store(result.state) is None


@pytest.mark.parametrize("step", [Step.REASON, Step.ASK_RETURN, Step.CONFIRM])
def test_an_emergency_escalates_and_keeps_the_extraction(step):
    flagged = Analysis(
        Intent.ANSWER, extraction(reason=AbsenceReason.OTHER, returns=None, followup=True)
    )
    result = decide(state_at(step), flagged, CTX)
    assert result.state.outcome == Outcome.ESCALATED
    assert result.state.escalation == Escalation.EMERGENCY
    assert result_to_store(result.state).needs_human_followup is True


# ---- reason step -----------------------------------------------------------------------


def test_no_reason_given_is_treated_as_unclear_and_ends_after_two_tries():
    not_given = answer(reason=AbsenceReason.NOT_GIVEN, returns=None)
    state, _ = run([say(Intent.YES), not_given, not_given])
    assert state.outcome == Outcome.INCOMPLETE
    assert result_to_store(state) is None


# ---- confirm step ----------------------------------------------------------------------


def test_saying_no_to_the_readback_restarts_once_then_gives_up():
    state, spoken = run([say(Intent.YES), answer(), say(Intent.NO)])
    assert state.step == Step.REASON
    assert state.extraction is None
    assert "tell me again" in spoken[2]
    state, _ = run([answer(), say(Intent.NO)], state)
    assert state.outcome == Outcome.INCOMPLETE
    assert result_to_store(state) is None  # an unconfirmed result is never saved


def test_a_correction_offered_instead_of_no_is_merged_and_read_back_again():
    state, spoken = run([say(Intent.YES), answer(), answer(returns=date(2026, 10, 6))])
    assert state.step == Step.CONFIRM
    assert state.extraction.expected_return_date == date(2026, 10, 6)
    assert "Tuesday, 6 October" in spoken[2]


def test_two_unclear_replies_at_confirm_end_incomplete_without_saving():
    state, _ = run([say(Intent.YES), answer(), say(Intent.UNCLEAR), say(Intent.UNCLEAR)])
    assert state.outcome == Outcome.INCOMPLETE
    assert result_to_store(state) is None


# ---- parent questions ------------------------------------------------------------------


def test_a_question_for_the_teacher_is_acknowledged_once_and_remembered():
    first = Analysis(Intent.YES, has_question=True)
    state, spoken = run([first, answer(), say(Intent.YES)])
    assert spoken[0].startswith("I'll pass that question to the teacher.")
    assert state.has_question is True
    assert "passed your question on" in spoken[2]
    assert not spoken[1].startswith("I'll pass")


# ---- invariants ------------------------------------------------------------------------


def test_deciding_after_the_call_has_ended_is_a_bug():
    ended, _ = run([say(Intent.NO)])
    with pytest.raises(ValueError):
        decide(ended, say(Intent.YES), CTX)


def test_state_survives_a_json_round_trip():
    state, _ = run([say(Intent.YES), answer(), say(Intent.UNCLEAR)])
    restored = ConversationState.model_validate_json(state.model_dump_json())
    assert restored == state


@pytest.mark.parametrize("step", ACTIVE_STEPS)
def test_endless_unclear_replies_always_terminate(step):
    state = state_at(step)
    for _ in range(10):
        if state.step == Step.ENDED:
            break
        state = decide(state, say(Intent.UNCLEAR), CTX).state
    assert state.step == Step.ENDED


def test_every_step_and_intent_combination_is_handled():
    """No combination raises, and every result either moves on or ends."""
    for step, intent, with_extraction in itertools.product(ACTIVE_STEPS, Intent, [False, True]):
        analysis = Analysis(intent, extraction() if with_extraction else None)
        result = decide(state_at(step), analysis, CTX)
        assert result.say
        assert result.ended or result.state != state_at(step) or result.state.unclear_count > 0


@pytest.mark.parametrize("step", ACTIVE_STEPS)
def test_a_technical_problem_ends_the_call_without_saving_or_naming_the_child(step):
    result = end_for_technical_problem(state_at(step), CTX)
    assert result.ended
    assert result.state.outcome == Outcome.INCOMPLETE
    assert result_to_store(result.state) is None
    assert "Asha" not in result.say
