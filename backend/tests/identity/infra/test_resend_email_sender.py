"""ResendEmailSender adapter — production EmailSender for magic-link delivery.

Before this adapter, V1 shipped only ``ConsoleEmailSender`` (logs the URL
instead of sending). Production deploys with ``RESEND_API_KEY`` set need a
real HTTP delivery path; the application layer's send_magic_link contract
is unchanged — same Protocol, different infra.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from vaultchain.identity.infra.email.resend import (
    SUBJECT,
    ResendEmailSender,
    ResendEmailSendError,
)


def _make_sender(**overrides: object) -> ResendEmailSender:
    kwargs: dict[str, object] = {
        "api_key": "re_test_xxxxxxxx",
        "from_address": "VaultChain <noreply@vaultchain.example>",
        "frontend_url": "https://app.example",
    }
    kwargs.update(overrides)
    return ResendEmailSender(**kwargs)  # type: ignore[arg-type]  # pragma: heterogeneous test kwargs dict


@pytest.mark.asyncio
@respx.mock
async def test_posts_to_resend_emails_endpoint_with_bearer_auth() -> None:
    route = respx.post("https://api.resend.com/emails").mock(
        return_value=httpx.Response(200, json={"id": "msg_123"})
    )
    sender = _make_sender()

    await sender.send_magic_link(to_email="user@x.io", raw_token="tok-abc", mode="signup")

    assert route.called
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer re_test_xxxxxxxx"
    assert request.headers["content-type"].startswith("application/json")
    body = json.loads(request.content)
    assert body["from"] == "VaultChain <noreply@vaultchain.example>"
    assert body["to"] == ["user@x.io"]
    assert body["subject"] == SUBJECT
    # The magic-link URL is interpolated with the same shape ConsoleEmailSender
    # uses, so the verify route on the SPA stays unchanged. Assert against the
    # plain-text body — the html body escapes "&" → "&amp;".
    expected_url = "https://app.example/auth/verify?token=tok-abc&mode=signup"
    assert expected_url in body["text"]
    assert "&amp;mode=signup" in body["html"]


@pytest.mark.asyncio
@respx.mock
async def test_strips_trailing_slash_on_frontend_url() -> None:
    respx.post("https://api.resend.com/emails").mock(
        return_value=httpx.Response(200, json={"id": "msg_123"})
    )
    sender = _make_sender(frontend_url="https://app.example/")

    await sender.send_magic_link(to_email="x@x.io", raw_token="t1", mode="login")

    body = json.loads(respx.calls.last.request.content)
    assert "//auth/verify" not in body["text"]
    assert "https://app.example/auth/verify?token=t1&mode=login" in body["text"]


@pytest.mark.asyncio
@respx.mock
async def test_login_mode_url_is_passed_through() -> None:
    respx.post("https://api.resend.com/emails").mock(
        return_value=httpx.Response(200, json={"id": "msg_456"})
    )
    sender = _make_sender()

    await sender.send_magic_link(to_email="user@x.io", raw_token="tok-xyz", mode="login")

    body = json.loads(respx.calls.last.request.content)
    assert "mode=login" in body["text"]


@pytest.mark.asyncio
@respx.mock
async def test_non_2xx_response_raises_send_error() -> None:
    """If Resend rejects the send (bad domain, unverified sender, rate limit),
    we surface a typed exception so the route returns 5xx and the user can
    click 'Resend' to create a fresh attempt.
    """
    respx.post("https://api.resend.com/emails").mock(
        return_value=httpx.Response(422, json={"message": "from is not a verified domain"})
    )
    sender = _make_sender()

    with pytest.raises(ResendEmailSendError) as exc_info:
        await sender.send_magic_link(to_email="x@x.io", raw_token="t", mode="signup")
    assert "422" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_network_failure_raises_send_error() -> None:
    """Connection refused / DNS failure also surfaces as ResendEmailSendError
    so the call site can treat all delivery failures uniformly.
    """
    respx.post("https://api.resend.com/emails").mock(side_effect=httpx.ConnectError("network down"))
    sender = _make_sender()

    with pytest.raises(ResendEmailSendError):
        await sender.send_magic_link(to_email="x@x.io", raw_token="t", mode="signup")
