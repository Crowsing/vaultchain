"""CSRF double-submit dependency — AC-phase1-identity-004-09.

State-changing methods (POST/PUT/PATCH/DELETE) must present an
``X-CSRF-Token`` header that matches the ``csrf`` cookie. GET / HEAD /
OPTIONS / TRACE are exempt because browsers won't include a cross-site
header on those.

Implemented as a callable class so tests can drive it without spinning
up FastAPI's dependency-injection plumbing.
"""

from __future__ import annotations

from typing import Protocol

from vaultchain.identity.domain.errors import CsrfFailed
from vaultchain.identity.infra.tokens.cookies import CSRF_COOKIE_NAME

CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class _RequestLike(Protocol):
    method: str

    @property
    def cookies(self) -> dict[str, str]: ...

    @property
    def headers(self) -> dict[str, str]: ...


class CsrfGuard:
    """No-arg callable: instantiate once at app startup, then ``Depends(CsrfGuard())``.

    Constant-time string comparison used so a near-miss header cannot be
    distinguished from a wholly wrong header by timing.
    """

    async def __call__(self, request: _RequestLike) -> None:
        if request.method.upper() in SAFE_METHODS:
            return

        cookie = request.cookies.get(CSRF_COOKIE_NAME)
        header_val = self._read_header(request)
        if not cookie or not header_val:
            raise CsrfFailed(details={"reason": "missing_token", "method": request.method})
        if not _constant_time_eq(cookie, header_val):
            raise CsrfFailed(details={"reason": "mismatch", "method": request.method})

    @staticmethod
    def _read_header(request: _RequestLike) -> str | None:
        # Starlette headers are case-insensitive but their dict view depends
        # on the implementation; iterate to stay tolerant of test stubs.
        for k, v in request.headers.items():
            if k.lower() == CSRF_HEADER.lower():
                return v
        return None


def _constant_time_eq(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    diff = 0
    for x, y in zip(a, b, strict=False):
        diff |= ord(x) ^ ord(y)
    return diff == 0


__all__ = ["CSRF_HEADER", "SAFE_METHODS", "CsrfGuard"]
