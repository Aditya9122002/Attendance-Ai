"""Twilio voice webhooks.

Purpose: answer Twilio's requests during a phone call with TwiML.
Input: Twilio's form-encoded POST and its X-Twilio-Signature header.
Output: TwiML (XML). Requests with a bad or missing signature get 403.
Dependencies: app.telephony, app.config.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.config import Settings, get_settings
from app.telephony import TelephonyNotConfigured, hello_twiml, public_url, signature_is_valid

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/twilio/voice", tags=["twilio"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


async def verified_form(request: Request, settings: Settings) -> dict[str, str]:
    """Return the form fields of a request that really came from Twilio, or raise."""
    form = await request.form()
    params = {key: str(value) for key, value in form.items()}
    try:
        url = public_url(settings, request.url.path, request.url.query)
        valid = signature_is_valid(settings, url, params, request.headers.get("X-Twilio-Signature"))
    except TelephonyNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Telephony is not configured") from exc
    if not valid:
        logger.warning("twilio_signature_rejected", extra={"path": request.url.path})
        raise HTTPException(status_code=403, detail="Invalid signature")
    return params


def twiml(body: str) -> Response:
    return Response(content=body, media_type="application/xml")


@router.post("/hello")
async def hello(request: Request, settings: SettingsDep) -> Response:
    """A call that only says hello, to prove the phone connection works."""
    params = await verified_form(request, settings)
    logger.info("twilio_hello", extra={"call_sid": params.get("CallSid", "")})
    return twiml(hello_twiml())
