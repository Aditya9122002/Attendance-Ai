"""Telephony helpers: build TwiML, check Twilio's signature, place a call.

Purpose: keep everything Twilio-specific in one small module, away from the call logic.
Input: settings, request details (url, form fields, signature), phone numbers.
Output: TwiML text, a yes/no signature check, a Twilio call SID.
Dependencies: the `twilio` package. No database and no language model.

Security: Twilio signs every webhook it sends. A request without a valid signature must be
refused, otherwise anyone who finds the public URL could drive our call flow. Twilio signs the
PUBLIC url it called (the tunnel or domain), not the local address the app sees, so the url is
rebuilt from PUBLIC_BASE_URL. Phone numbers are personal data: never log form fields.
"""

import re
from collections.abc import Callable, Mapping
from typing import Any

from twilio.request_validator import RequestValidator
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

from app.config import Settings

E164 = re.compile(r"^\+[1-9]\d{7,14}$")
HELLO_LINE = "Hello. This is a test call from the attendance assistant. Goodbye."
HELLO_LANGUAGE = "en-IN"


class TelephonyNotConfigured(Exception):
    """A Twilio setting that is needed is missing."""


def public_url(settings: Settings, path: str, query: str = "") -> str:
    """The full public url Twilio used for this path."""
    if not settings.public_base_url:
        raise TelephonyNotConfigured("PUBLIC_BASE_URL is not set")
    base = settings.public_base_url.rstrip("/")
    return f"{base}{path}" + (f"?{query}" if query else "")


def signature_is_valid(
    settings: Settings, url: str, params: Mapping[str, str], signature: str | None
) -> bool:
    """True only if Twilio's signature matches this url and these form fields."""
    if settings.twilio_auth_token is None:
        raise TelephonyNotConfigured("TWILIO_AUTH_TOKEN is not set")
    if not signature:
        return False
    validator = RequestValidator(settings.twilio_auth_token.get_secret_value())
    return validator.validate(url, dict(params), signature)


def hello_twiml() -> str:
    response = VoiceResponse()
    response.say(HELLO_LINE, language=HELLO_LANGUAGE)
    response.hangup()
    return str(response)


def place_hello_call(
    settings: Settings,
    to_number: str,
    client_factory: Callable[[str, str], Any] = Client,
) -> str:
    """Ask Twilio to call `to_number` and play the hello message. Returns the call SID."""
    if not E164.match(to_number):
        raise ValueError("The number must be in international format, like +919800000001")
    missing = [
        name
        for name, value in (
            ("TWILIO_ACCOUNT_SID", settings.twilio_account_sid),
            ("TWILIO_AUTH_TOKEN", settings.twilio_auth_token),
            ("TWILIO_FROM_NUMBER", settings.twilio_from_number),
            ("PUBLIC_BASE_URL", settings.public_base_url),
        )
        if not value
    ]
    if missing:
        raise TelephonyNotConfigured("Missing settings: " + ", ".join(missing))
    client = client_factory(
        settings.twilio_account_sid, settings.twilio_auth_token.get_secret_value()
    )
    call = client.calls.create(
        to=to_number,
        from_=settings.twilio_from_number,
        url=public_url(settings, "/twilio/voice/hello"),
    )
    return call.sid
