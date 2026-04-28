"""In-memory ``EmailSender`` fake — captures calls so tests can assert."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class _Sent:
    to_email: str
    raw_token: str
    mode: str


class FakeEmailSender:
    def __init__(self) -> None:
        self.sent: list[_Sent] = []

    async def send_magic_link(
        self,
        *,
        to_email: str,
        raw_token: str,
        mode: str,
    ) -> None:
        self.sent.append(_Sent(to_email=to_email, raw_token=raw_token, mode=mode))


__all__ = ["FakeEmailSender"]
