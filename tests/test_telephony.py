import logging
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from twilio.request_validator import RequestValidator

from app.config import Settings, get_settings
from app.main import app
from app.telephony import (
    TelephonyNotConfigured,
    hello_twiml,
    place_hello_call,
    public_url,
    signature_is_valid,
)

TOKEN = "test-token-not-real"
BASE = "https://example.ngrok-free.app"
FORM = {"CallSid": "CA123", "From": "+14155550100", "To": "+919800000001"}


def make_settings(**overrides) -> Settings:
    values = {
        "twilio_account_sid": "ACtest",
        "twilio_auth_token": SecretStr(TOKEN),
        "twilio_from_number": "+14155550100",
        "public_base_url": BASE,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def sign(path: str, params: dict[str, str], query: str = "") -> str:
    url = f"{BASE}{path}" + (f"?{query}" if query else "")
    return RequestValidator(TOKEN).compute_signature(url, params)


@pytest.fixture
def settings_override():
    def use(settings: Settings):
        app.dependency_overrides[get_settings] = lambda: settings

    yield use
    app.dependency_overrides.clear()


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        yield c


def test_the_public_url_ignores_a_trailing_slash_and_keeps_the_query():
    settings = make_settings(public_base_url=BASE + "/")
    assert public_url(settings, "/twilio/voice/hello") == f"{BASE}/twilio/voice/hello"
    assert public_url(settings, "/x", "a=1") == f"{BASE}/x?a=1"


def test_the_public_url_needs_a_base_url():
    with pytest.raises(TelephonyNotConfigured):
        public_url(make_settings(public_base_url=None), "/x")


def test_a_correct_signature_is_accepted_and_a_wrong_one_is_not():
    settings = make_settings()
    url = f"{BASE}/twilio/voice/hello"
    good = RequestValidator(TOKEN).compute_signature(url, FORM)
    assert signature_is_valid(settings, url, FORM, good) is True
    assert signature_is_valid(settings, url, FORM, "bad") is False
    assert signature_is_valid(settings, url, FORM, None) is False
    assert signature_is_valid(settings, url, {**FORM, "To": "+910000000000"}, good) is False


def test_the_hello_twiml_says_a_line_and_hangs_up():
    xml = hello_twiml()
    assert "<Say" in xml and 'language="en-IN"' in xml
    assert xml.index("<Say") < xml.index("<Hangup")


async def test_a_signed_hello_request_gets_twiml(client, settings_override):
    settings_override(make_settings())
    response = await client.post(
        "/twilio/voice/hello",
        data=FORM,
        headers={"X-Twilio-Signature": sign("/twilio/voice/hello", FORM)},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert "<Say" in response.text


async def test_a_request_with_a_bad_or_missing_signature_is_refused(client, settings_override):
    settings_override(make_settings())
    bad = await client.post(
        "/twilio/voice/hello", data=FORM, headers={"X-Twilio-Signature": "forged"}
    )
    missing = await client.post("/twilio/voice/hello", data=FORM)
    assert bad.status_code == 403
    assert missing.status_code == 403


async def test_a_signature_for_another_path_is_refused(client, settings_override):
    settings_override(make_settings())
    response = await client.post(
        "/twilio/voice/hello",
        data=FORM,
        headers={"X-Twilio-Signature": sign("/twilio/voice/other", FORM)},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("missing", [{"twilio_auth_token": None}, {"public_base_url": None}])
async def test_the_webhook_refuses_to_serve_when_telephony_is_not_configured(
    client, settings_override, missing
):
    settings_override(make_settings(**missing))
    response = await client.post(
        "/twilio/voice/hello", data=FORM, headers={"X-Twilio-Signature": "x"}
    )
    assert response.status_code == 503


async def test_phone_numbers_are_never_logged(client, settings_override, caplog):
    settings_override(make_settings())
    with caplog.at_level(logging.DEBUG):
        await client.post(
            "/twilio/voice/hello",
            data=FORM,
            headers={"X-Twilio-Signature": sign("/twilio/voice/hello", FORM)},
        )
        await client.post("/twilio/voice/hello", data=FORM)
    logged = " ".join(record.getMessage() + str(record.__dict__) for record in caplog.records)
    assert "+14155550100" not in logged
    assert "+919800000001" not in logged


class FakeClient:
    created: dict = {}

    def __init__(self, sid, token):
        FakeClient.created = {"sid": sid, "token": token}
        self.calls = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        FakeClient.created["call"] = kwargs
        return SimpleNamespace(sid="CAfake")


def test_placing_the_hello_call_sends_the_public_hello_url():
    sid = place_hello_call(make_settings(), "+919800000001", client_factory=FakeClient)
    assert sid == "CAfake"
    assert FakeClient.created["sid"] == "ACtest"
    assert FakeClient.created["call"] == {
        "to": "+919800000001",
        "from_": "+14155550100",
        "url": f"{BASE}/twilio/voice/hello",
    }


@pytest.mark.parametrize("number", ["9800000001", "+0123456", "abc", "+91 98000 00001", ""])
def test_a_number_not_in_international_format_is_refused(number):
    with pytest.raises(ValueError):
        place_hello_call(make_settings(), number, client_factory=FakeClient)


def test_a_missing_setting_is_named_without_showing_secrets():
    settings = make_settings(twilio_from_number=None, public_base_url=None)
    with pytest.raises(TelephonyNotConfigured) as error:
        place_hello_call(settings, "+919800000001", client_factory=FakeClient)
    message = str(error.value)
    assert "TWILIO_FROM_NUMBER" in message and "PUBLIC_BASE_URL" in message
    assert TOKEN not in message
