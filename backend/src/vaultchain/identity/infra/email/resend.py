"""Resend HTTP API ``EmailSender`` — production magic-link delivery.

V1 shipped ``ConsoleEmailSender`` only (logs the URL); this adapter is the
swap-in for production where ``RESEND_API_KEY`` is set. Same Protocol,
different infra — composition.py picks one based on settings.
"""

from __future__ import annotations

import html

import httpx
import structlog

#: Reused across console + Resend so dev grep / prod operator UX match.
SUBJECT = "Your VaultChain magic link"
EMAIL_LOG_EVENT = "identity.email.magic_link.resend"

_RESEND_ENDPOINT = "https://api.resend.com/emails"
_DEFAULT_TIMEOUT = 10.0  # seconds — magic-link issuance is user-blocking
_HTTP_REDIRECT_FLOOR = 300

_log = structlog.get_logger(__name__)


class ResendEmailSendError(RuntimeError):
    """Raised on any non-2xx response or transport error from Resend."""


class ResendEmailSender:
    """``EmailSender`` adapter that POSTs to the Resend HTTP API.

    The application layer treats send failures as transient — a raised
    exception bubbles up to the route, which returns 5xx; the user clicks
    'Resend' to create a fresh magic-link row.
    """

    def __init__(
        self,
        *,
        api_key: str,
        from_address: str,
        frontend_url: str,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key
        self._from = from_address
        self._frontend_url = frontend_url.rstrip("/")
        self._timeout = timeout

    async def send_magic_link(
        self,
        *,
        to_email: str,
        raw_token: str,
        mode: str,
    ) -> None:
        url = f"{self._frontend_url}/auth/verify?token={raw_token}&mode={mode}"
        payload = {
            "from": self._from,
            "to": [to_email],
            "subject": SUBJECT,
            "html": _render_html(url),
            "text": _render_text(url),
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(_RESEND_ENDPOINT, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise ResendEmailSendError(f"resend transport error: {exc}") from exc

        if response.status_code >= _HTTP_REDIRECT_FLOOR:
            raise ResendEmailSendError(
                f"resend rejected send: HTTP {response.status_code} {response.text[:200]}"
            )

        _log.info(EMAIL_LOG_EVENT, to=to_email, mode=mode, message_id=_extract_id(response))


def _render_html(verify_url: str) -> str:
    safe = html.escape(verify_url, quote=True)
    return (
        '<!doctype html><html><body style="font-family:sans-serif">'
        "<h2>Sign in to VaultChain</h2>"
        f"<p>Click the link below to continue. It expires in 15 minutes.</p>"
        f'<p><a href="{safe}">{safe}</a></p>'
        "<p>If you didn't request this, you can ignore this email.</p>"
        "</body></html>"
    )


def _render_text(verify_url: str) -> str:
    return (
        "Sign in to VaultChain\n\n"
        "Click the link below to continue. It expires in 15 minutes.\n\n"
        f"{verify_url}\n\n"
        "If you didn't request this, you can ignore this email.\n"
    )


def _extract_id(response: httpx.Response) -> str | None:
    try:
        data = response.json()
    except ValueError:
        return None
    return data.get("id") if isinstance(data, dict) else None


__all__ = [
    "EMAIL_LOG_EVENT",
    "SUBJECT",
    "ResendEmailSender",
    "ResendEmailSendError",
]
