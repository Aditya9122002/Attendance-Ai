"""A crude keyword stand-in for a language model, for offline demos only.

Purpose: let scripts/simulate_call.py run the whole call loop without a network or an API key.
Input: the same system/user/schema that a real model client gets.
Output: JSON text that follows the schema, chosen by simple keyword rules.
Dependencies: none.

It is NOT a model. It knows a few English and Hinglish keywords, so it is only good for
trying the conversation flow. Never use its answers to judge how well a real model does.
"""

import json
import re
from datetime import date, timedelta
from typing import Any

from app.llm.base import LlmError

_OPT_OUT = ("stop calling", "do not call", "don't call", "dont call", "remove my number")
_WANTS_HUMAN = ("speak to", "talk to", "teacher", "principal", "real person", "human")
_UPSET = ("stupid", "useless", "idiot", "shut up", "nonsense")
_WRONG_PERSON = ("wrong number", "not the parent", "don't know the child", "dont know the child")
_CALL_LATER = ("call later", "call me later", "call back", "busy")
_NO = re.compile(r"\b(no|nahi|nako|wrong|incorrect|not right|not correct)\b")
_YES = re.compile(r"\b(yes|yep|haan|ho|correct|right|speaking)\b")

_REASONS = (  # checked in this order
    ("family_event", ("wedding", "puja", "function", "funeral", "death", "died")),
    ("travel", ("trip", "travel", "holiday", "out of town", "village")),
    ("transport", ("bus", "van", "auto", "rickshaw")),
    ("illness", ("fever", "sick", "cold", "cough", "unwell", "doctor", "stomach", "vomit")),
    ("other", ("accident", "injury", "hospital")),
)
_EMERGENCY = ("hospital", "accident", "emergency", "died", "death", "ambulance")
# The child's whereabouts are in doubt: a person must check (see extraction prompt v3).
_WHEREABOUTS = (
    "don't know where",
    "dont know where",
    "left home",
    "left the home",
    "in school",
    "went to school",
    "school mein",
    "nikla",
    "nikli",
)
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def _reply_text(user: str) -> str:
    return user.split("<parent_reply>\n", 1)[1].rsplit("\n</parent_reply>", 1)[0]


def _today(user: str) -> date | None:
    match = _ISO_DATE.search(user.split("\n", 1)[0])
    return date(*map(int, match.groups())) if match else None


def _has_reason(text: str) -> bool:
    return any(word in text for _, words in _REASONS for word in words)


def _return_date(text: str, today: date) -> date | None:
    iso = _ISO_DATE.search(text)
    if iso:
        try:
            return date(*map(int, iso.groups()))
        except ValueError:
            return None
    if "day after tomorrow" in text or "parso" in text:
        return today + timedelta(days=2)
    if "tomorrow" in text or re.search(r"\bkal\b", text):
        return today + timedelta(days=1)
    for index, name in enumerate(_WEEKDAYS):
        if name in text:
            return today + timedelta(days=(index - today.weekday()) % 7 or 7)
    return None


def _intent(text: str) -> dict[str, Any]:
    if any(p in text for p in _OPT_OUT):
        intent = "opt_out"
    elif any(p in text for p in _WANTS_HUMAN):
        intent = "wants_human"
    elif any(p in text for p in _UPSET):
        intent = "upset"
    elif any(p in text for p in _WRONG_PERSON):
        intent = "wrong_person"
    elif any(p in text for p in _CALL_LATER):
        intent = "call_later"
    elif _has_reason(text) or _ISO_DATE.search(text) or any(d in text for d in _WEEKDAYS):
        intent = "answer"  # also covers "no, he is back on Monday"
    elif "tomorrow" in text or re.search(r"\b(kal|parso)\b", text):
        intent = "answer"
    elif _NO.search(text):
        intent = "no"
    elif _YES.search(text):
        intent = "yes"
    else:
        intent = "unclear"
    has_question = any(word in text for word in ("homework", "fees", "exam"))
    return {"intent": intent, "has_question": has_question}


def _extraction(text: str, today: date) -> dict[str, Any]:
    if any(phrase in text for phrase in _WHEREABOUTS):
        return {
            "reason": "not_given",
            "expected_return_date": None,
            "needs_human_followup": True,
            "confidence": 0.8,
        }
    reason = "not_given"
    for name, words in _REASONS:
        if any(word in text for word in words):
            reason = name
            break
    expected = _return_date(text, today)
    return {
        "reason": reason,
        "expected_return_date": expected.isoformat() if expected else None,
        "needs_human_followup": any(word in text for word in _EMERGENCY),
        "confidence": 0.8,
    }


class KeywordDemoLlm:
    async def generate_json(self, *, system: str, user: str, schema: dict[str, Any]) -> str:
        if "<parent_reply>" not in user:
            raise LlmError("demo model: unexpected message")
        text = _reply_text(user).lower()
        properties = schema.get("properties", {})
        if "intent" in properties:
            return json.dumps(_intent(text))
        if "reason" in properties:
            today = _today(user)
            if today is None:
                raise LlmError("demo model: no date in message")
            return json.dumps(_extraction(text, today))
        raise LlmError("demo model: unknown schema")
