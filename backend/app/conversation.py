"""Conversation manager: the decision logic for one phone call.

Purpose: decide what the agent says next and when the call ends.
Input: the current ConversationState, an Analysis of what the parent just said, and the
CallContext (school, guardian and student names).
Output: a TurnResult holding the new state and the agent's next line.
Dependencies: app.extraction (data types only). No database, no network, no language model.

Principle: a language model UNDERSTANDS what the parent said (that produces an Analysis);
this code DECIDES what happens next. The safety rules below live here, in plain code that
tests can cover completely:
- No line spoken before the caller is confirmed contains the child's name.
- Opt-out, wrong person, a request for a human, an upset parent, or an emergency always win
  over the normal flow, in every step.
- Unclear replies are retried a bounded number of times, then the call ends as incomplete.
- Only a confirmed result, or an emergency, is ever handed on for saving. Nothing is guessed.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.extraction import AbsenceReason, Extraction

MAX_UNCLEAR = 2  # consecutive unclear replies tolerated in one step
MAX_CORRECTIONS = 1  # times the parent may say the read-back is wrong


class Step(StrEnum):
    IDENTITY = "identity"
    REASON = "reason"
    ASK_RETURN = "ask_return"
    CONFIRM = "confirm"
    ENDED = "ended"


class Outcome(StrEnum):
    COMPLETED = "completed"
    ESCALATED = "escalated"
    WRONG_PERSON = "wrong_person"
    OPTED_OUT = "opted_out"
    CALL_LATER = "call_later"
    INCOMPLETE = "incomplete"


class Escalation(StrEnum):
    EMERGENCY = "emergency"
    WANTS_HUMAN = "wants_human"
    UPSET = "upset"


class Intent(StrEnum):
    YES = "yes"
    NO = "no"
    WRONG_PERSON = "wrong_person"
    CALL_LATER = "call_later"
    OPT_OUT = "opt_out"
    WANTS_HUMAN = "wants_human"
    UPSET = "upset"
    ANSWER = "answer"  # the reply carries information (used with an Extraction)
    UNCLEAR = "unclear"  # includes silence and noise


@dataclass(frozen=True)
class CallContext:
    school_name: str
    guardian_name: str
    student_name: str  # first name only; this is the only child detail ever spoken
    language: str = "en"


@dataclass(frozen=True)
class Analysis:
    intent: Intent
    extraction: Extraction | None = None
    has_question: bool = False  # the parent asked something we cannot answer


class ConversationState(BaseModel):
    """Everything that must survive between turns. Serialises to JSON for storage."""

    model_config = ConfigDict(frozen=True)

    step: Step = Step.IDENTITY
    unclear_count: int = 0
    correction_count: int = 0
    asked_return: bool = False
    extraction: Extraction | None = None
    has_question: bool = False
    outcome: Outcome | None = None
    escalation: Escalation | None = None


@dataclass(frozen=True)
class TurnResult:
    state: ConversationState
    say: str

    @property
    def ended(self) -> bool:
        return self.state.step == Step.ENDED


# The lines the agent speaks. Keyed by language so Stage 9 can add Hindi, Marathi and others.
# Do not promise anything the system cannot yet do (for example, a guaranteed callback).
PHRASES: dict[str, dict[str, str]] = {
    "en": {
        "opening": (
            "Hello, this is an automated assistant calling from {school}. "
            "Am I speaking with {guardian}, a parent or guardian of a student at {school}?"
        ),
        "identity_retry": (
            "Sorry, I didn't catch that. "
            "Am I speaking with {guardian}, a parent or guardian of a student at {school}?"
        ),
        "purpose": (
            "Thank you. We noticed {student} was not in school today. Could you tell me the reason?"
        ),
        "reason_retry": "Sorry, I didn't catch that. Could you tell me why {student} was absent?",
        "ask_return": "Thank you. When do you expect {student} to return?",
        "readback": "So {student} was absent because of {reason}{when}. Is that right?",
        "confirm_retry": "Sorry, I didn't catch that. ",
        "correction": (
            "Sorry about that. Could you tell me again why {student} was absent, "
            "and when {student} will return?"
        ),
        "question_prefix": "I'll pass that question to the teacher. ",
        "close_completed": "Thank you. I've noted this for {student}'s teacher. Goodbye.",
        "close_completed_question": (
            "Thank you. I've noted this for {student}'s teacher, "
            "and I've passed your question on. Goodbye."
        ),
        "close_wrong_person": "Sorry to have disturbed you. Goodbye.",
        "close_opt_out": (
            "Understood. We'll stop automated calls to this number. "
            "Sorry for the disturbance. Goodbye."
        ),
        "close_call_later": "No problem, we'll try again later. Goodbye.",
        "close_escalated": (
            "I understand. I'll let the school know so that a person can follow up with you. "
            "Thank you, goodbye."
        ),
        "close_emergency": (
            "I'm sorry to hear that. I'm letting the school know right away so that a person "
            "can follow up with you. Thank you, goodbye."
        ),
        "close_incomplete": (
            "Sorry, I'm having trouble understanding. We'll try again later. Goodbye."
        ),
        "reason_illness": "illness",
        "reason_family_event": "a family event",
        "reason_travel": "travel",
        "reason_transport": "a transport problem",
        "reason_other": "a personal reason",
        "reason_not_given": "a reason that was not stated",
    }
}

_RETRY_KEY = {
    Step.IDENTITY: "identity_retry",
    Step.REASON: "reason_retry",
}


def _say(ctx: CallContext, key: str, **extra: str) -> str:
    phrases = PHRASES.get(ctx.language, PHRASES["en"])
    return phrases[key].format(
        school=ctx.school_name, guardian=ctx.guardian_name, student=ctx.student_name, **extra
    )


def _spoken_date(day: date) -> str:
    return f"{day:%A}, {day.day} {day:%B}"


def _readback(state: ConversationState, ctx: CallContext) -> str:
    extraction = state.extraction
    assert extraction is not None  # CONFIRM is only entered with an extraction
    reason = _say(ctx, f"reason_{extraction.reason.value}")
    when = (
        f" and will return on {_spoken_date(extraction.expected_return_date)}"
        if extraction.expected_return_date
        else ""
    )
    return _say(ctx, "readback", reason=reason, when=when)


def opening(ctx: CallContext) -> str:
    """The first thing the agent says. Contains the school and guardian, never the child."""
    return _say(ctx, "opening")


def result_to_store(state: ConversationState) -> Extraction | None:
    """The only extraction that may be saved: a confirmed one, or one that flagged an emergency."""
    if state.step != Step.ENDED:
        return None
    if state.outcome == Outcome.COMPLETED:
        return state.extraction
    if state.outcome == Outcome.ESCALATED and state.escalation == Escalation.EMERGENCY:
        return state.extraction
    return None


def _merge(old: Extraction | None, new: Extraction | None) -> Extraction | None:
    """Combine an earlier extraction with a later reply (for example, a date given on its own)."""
    if old is None:
        return new
    if new is None:
        return old
    return old.model_copy(
        update={
            "reason": new.reason if new.reason != AbsenceReason.NOT_GIVEN else old.reason,
            "expected_return_date": new.expected_return_date or old.expected_return_date,
            "needs_human_followup": old.needs_human_followup or new.needs_human_followup,
            "confidence": min(old.confidence, new.confidence),
        }
    )


def _end(
    state: ConversationState,
    ctx: CallContext,
    outcome: Outcome,
    key: str,
    escalation: Escalation | None = None,
) -> TurnResult:
    ended = state.model_copy(
        update={"step": Step.ENDED, "outcome": outcome, "escalation": escalation}
    )
    return TurnResult(state=ended, say=_say(ctx, key))


def _unclear(state: ConversationState, ctx: CallContext) -> TurnResult:
    count = state.unclear_count + 1
    if count >= MAX_UNCLEAR:
        return _end(state, ctx, Outcome.INCOMPLETE, "close_incomplete")
    retry = state.model_copy(update={"unclear_count": count})
    if state.step == Step.CONFIRM:
        return TurnResult(retry, _say(ctx, "confirm_retry") + _readback(retry, ctx))
    return TurnResult(retry, _say(ctx, _RETRY_KEY[state.step]))


def _global_override(
    state: ConversationState, analysis: Analysis, ctx: CallContext
) -> TurnResult | None:
    """Rules that apply in every step and always win over the normal flow."""
    intent = analysis.intent
    if intent == Intent.OPT_OUT:
        return _end(state, ctx, Outcome.OPTED_OUT, "close_opt_out")
    if intent == Intent.WRONG_PERSON:
        return _end(state, ctx, Outcome.WRONG_PERSON, "close_wrong_person")
    if intent == Intent.CALL_LATER:
        return _end(state, ctx, Outcome.CALL_LATER, "close_call_later")
    if intent == Intent.WANTS_HUMAN:
        return _end(state, ctx, Outcome.ESCALATED, "close_escalated", Escalation.WANTS_HUMAN)
    if intent == Intent.UPSET:
        return _end(state, ctx, Outcome.ESCALATED, "close_escalated", Escalation.UPSET)
    extraction = analysis.extraction
    if extraction is not None and extraction.needs_human_followup and state.step != Step.IDENTITY:
        flagged = state.model_copy(update={"extraction": _merge(state.extraction, extraction)})
        return _end(flagged, ctx, Outcome.ESCALATED, "close_emergency", Escalation.EMERGENCY)
    return None


def _identity(state: ConversationState, analysis: Analysis, ctx: CallContext) -> TurnResult:
    if analysis.intent == Intent.YES:
        confirmed = state.model_copy(update={"step": Step.REASON, "unclear_count": 0})
        return TurnResult(confirmed, _say(ctx, "purpose"))
    if analysis.intent == Intent.NO:
        return _end(state, ctx, Outcome.WRONG_PERSON, "close_wrong_person")
    # Anything else, including a reply full of information, does NOT unlock the child's details.
    return _unclear(state, ctx)


def _reason(state: ConversationState, analysis: Analysis, ctx: CallContext) -> TurnResult:
    extraction = analysis.extraction
    if analysis.intent != Intent.ANSWER or extraction is None:
        return _unclear(state, ctx)
    if extraction.reason == AbsenceReason.NOT_GIVEN:
        return _unclear(state, ctx)
    if extraction.expected_return_date is None and not state.asked_return:
        asking = state.model_copy(
            update={
                "step": Step.ASK_RETURN,
                "extraction": extraction,
                "asked_return": True,
                "unclear_count": 0,
            }
        )
        return TurnResult(asking, _say(ctx, "ask_return"))
    confirming = state.model_copy(
        update={"step": Step.CONFIRM, "extraction": extraction, "unclear_count": 0}
    )
    return TurnResult(confirming, _readback(confirming, ctx))


def _ask_return(state: ConversationState, analysis: Analysis, ctx: CallContext) -> TurnResult:
    # Asked once only. Whether or not a date came back, move on to the read-back.
    merged = state.extraction
    if analysis.intent == Intent.ANSWER and analysis.extraction is not None:
        merged = _merge(state.extraction, analysis.extraction)
    confirming = state.model_copy(
        update={"step": Step.CONFIRM, "extraction": merged, "unclear_count": 0}
    )
    return TurnResult(confirming, _readback(confirming, ctx))


def _confirm(state: ConversationState, analysis: Analysis, ctx: CallContext) -> TurnResult:
    if analysis.intent == Intent.YES:
        key = "close_completed_question" if state.has_question else "close_completed"
        return _end(state, ctx, Outcome.COMPLETED, key)

    offered_correction = analysis.intent == Intent.ANSWER and analysis.extraction is not None
    if analysis.intent == Intent.NO or offered_correction:
        corrections = state.correction_count + 1
        if corrections > MAX_CORRECTIONS:
            return _end(state, ctx, Outcome.INCOMPLETE, "close_incomplete")
        if offered_correction:
            merged = _merge(state.extraction, analysis.extraction)
            again = state.model_copy(
                update={"extraction": merged, "correction_count": corrections, "unclear_count": 0}
            )
            return TurnResult(again, _readback(again, ctx))
        restart = state.model_copy(
            update={
                "step": Step.REASON,
                "extraction": None,
                "asked_return": False,
                "correction_count": corrections,
                "unclear_count": 0,
            }
        )
        return TurnResult(restart, _say(ctx, "correction"))

    return _unclear(state, ctx)


_HANDLERS = {
    Step.IDENTITY: _identity,
    Step.REASON: _reason,
    Step.ASK_RETURN: _ask_return,
    Step.CONFIRM: _confirm,
}


def decide(state: ConversationState, analysis: Analysis, ctx: CallContext) -> TurnResult:
    """One turn: given what the parent said, return the new state and what to say next."""
    if state.step == Step.ENDED:
        raise ValueError("The call has already ended")
    if analysis.has_question:
        state = state.model_copy(update={"has_question": True})

    result = _global_override(state, analysis, ctx) or _HANDLERS[state.step](state, analysis, ctx)

    if analysis.has_question and not result.ended:
        result = TurnResult(result.state, _say(ctx, "question_prefix") + result.say)
    return result
