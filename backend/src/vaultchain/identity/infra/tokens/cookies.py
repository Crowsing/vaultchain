"""Cookie helpers — set/clear the three session cookies on a response.

Cookie attributes per architecture-decisions Section 4 + AC-phase1-identity-004-10:

- ``vc_at``  — httpOnly, Secure, SameSite=Lax, path=/, max_age=900
- ``vc_rt``  — httpOnly, Secure, SameSite=Lax, path=/api/v1/auth/refresh, max_age=2592000
- ``csrf``   — httpOnly=False, Secure, SameSite=Lax, path=/, max_age=900

A ``cookies_secure`` flag lets local dev (`http://localhost`) drop the Secure
attribute so cookies actually get set; production wiring leaves it True.
"""

from __future__ import annotations

from typing import Any, Protocol

ACCESS_COOKIE_NAME = "vc_at"
REFRESH_COOKIE_NAME = "vc_rt"
CSRF_COOKIE_NAME = "csrf"

ACCESS_TOKEN_TTL = 15 * 60  # seconds (matches Redis TTL)
REFRESH_TOKEN_TTL = 30 * 24 * 60 * 60  # 30 days
CSRF_TOKEN_TTL = 15 * 60  # rotates with access cookie

REFRESH_COOKIE_PATH = "/api/v1/auth/refresh"
ROOT_PATH = "/"
SAME_SITE_LAX = "lax"


class _CookieResponse(Protocol):
    """Subset of the `Response.set_cookie` / `delete_cookie` shape that
    FastAPI / Starlette responses expose. Typed structurally so we work
    with both the real `Response` and bespoke test stubs; ``Any`` keeps
    the kwargs signature compatible with Starlette's permissive
    `set_cookie` (most params optional with sentinel defaults).
    """

    def set_cookie(self, *args: Any, **kwargs: Any) -> None: ...

    def delete_cookie(self, *args: Any, **kwargs: Any) -> None: ...


def set_session_cookies(
    response: _CookieResponse,
    *,
    access_token: str,
    refresh_token: str,
    csrf_token: str,
    cookies_secure: bool = True,
) -> None:
    """Apply all three session cookies in one call.

    The helper is the seam where AC-phase1-identity-004-10's exact
    attributes are written; route handlers in identity-005 consume it.
    """
    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=access_token,
        max_age=ACCESS_TOKEN_TTL,
        path=ROOT_PATH,
        httponly=True,
        secure=cookies_secure,
        samesite=SAME_SITE_LAX,
    )
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=REFRESH_TOKEN_TTL,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=cookies_secure,
        samesite=SAME_SITE_LAX,
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        max_age=CSRF_TOKEN_TTL,
        path=ROOT_PATH,
        httponly=False,  # double-submit pattern needs JS read access
        secure=cookies_secure,
        samesite=SAME_SITE_LAX,
    )


def clear_session_cookies(response: _CookieResponse) -> None:
    """Remove the three session cookies — used on logout."""
    response.delete_cookie(ACCESS_COOKIE_NAME, path=ROOT_PATH)
    response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)
    response.delete_cookie(CSRF_COOKIE_NAME, path=ROOT_PATH)


__all__ = [
    "ACCESS_COOKIE_NAME",
    "ACCESS_TOKEN_TTL",
    "CSRF_COOKIE_NAME",
    "CSRF_TOKEN_TTL",
    "REFRESH_COOKIE_NAME",
    "REFRESH_COOKIE_PATH",
    "REFRESH_TOKEN_TTL",
    "ROOT_PATH",
    "SAME_SITE_LAX",
    "clear_session_cookies",
    "set_session_cookies",
]
