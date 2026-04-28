"""Cookie helpers — set/clear the three session cookies on a response.

Cookie attributes per architecture-decisions Section 4 + AC-phase1-identity-004-10:

- ``vc_at``  — httpOnly, Secure, SameSite=Lax, path=/, max_age=900
- ``vc_rt``  — httpOnly, Secure, SameSite=Lax, path=/api/v1/auth/refresh, max_age=2592000
- ``csrf``   — httpOnly=False, Secure, SameSite=Lax, path=/, max_age=900

Admin sessions reuse the helper with overrides per phase1-admin-002a:

- ``admin_at``   — path=/admin/api/v1/
- ``admin_rt``   — path=/admin/api/v1/auth/refresh, SameSite=Strict
- ``admin_csrf`` — path=/admin/api/v1/

A ``cookies_secure`` flag lets local dev (`http://localhost`) drop the Secure
attribute so cookies actually get set; production wiring leaves it True.
"""

from __future__ import annotations

from dataclasses import dataclass
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
SAME_SITE_STRICT = "strict"

# Admin cookie names + paths per phase1-admin-002a Architecture pointers.
ADMIN_ACCESS_COOKIE_NAME = "admin_at"
ADMIN_REFRESH_COOKIE_NAME = "admin_rt"
ADMIN_CSRF_COOKIE_NAME = "admin_csrf"
ADMIN_PRE_TOTP_COOKIE_NAME = "admin_pre_totp"

ADMIN_BASE_PATH = "/admin/api/v1/"
ADMIN_REFRESH_COOKIE_PATH = "/admin/api/v1/auth/refresh"
ADMIN_PRE_TOTP_COOKIE_PATH = "/admin/api/v1/auth/totp/verify"
ADMIN_PRE_TOTP_TTL = 5 * 60  # 5 minutes; matches Redis TTL on the cache.


@dataclass(frozen=True)
class CookieConfig:
    """Routes (user vs admin) carry distinct cookie names + paths.

    Frozen so the config is picked at app-wire time, not per-request.
    """

    access_name: str = ACCESS_COOKIE_NAME
    refresh_name: str = REFRESH_COOKIE_NAME
    csrf_name: str = CSRF_COOKIE_NAME
    access_path: str = ROOT_PATH
    refresh_path: str = REFRESH_COOKIE_PATH
    csrf_path: str = ROOT_PATH
    refresh_same_site: str = SAME_SITE_LAX
    access_same_site: str = SAME_SITE_LAX
    csrf_same_site: str = SAME_SITE_LAX


USER_COOKIE_CONFIG = CookieConfig()
ADMIN_COOKIE_CONFIG = CookieConfig(
    access_name=ADMIN_ACCESS_COOKIE_NAME,
    refresh_name=ADMIN_REFRESH_COOKIE_NAME,
    csrf_name=ADMIN_CSRF_COOKIE_NAME,
    access_path=ADMIN_BASE_PATH,
    refresh_path=ADMIN_REFRESH_COOKIE_PATH,
    csrf_path=ADMIN_BASE_PATH,
    refresh_same_site=SAME_SITE_STRICT,
)


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
    config: CookieConfig = USER_COOKIE_CONFIG,
) -> None:
    """Apply all three session cookies in one call.

    The helper is the seam where AC-phase1-identity-004-10's exact
    attributes are written; route handlers in identity-005 consume it
    with the default user config and admin routes pass
    ``config=ADMIN_COOKIE_CONFIG``.
    """
    response.set_cookie(
        key=config.access_name,
        value=access_token,
        max_age=ACCESS_TOKEN_TTL,
        path=config.access_path,
        httponly=True,
        secure=cookies_secure,
        samesite=config.access_same_site,
    )
    response.set_cookie(
        key=config.refresh_name,
        value=refresh_token,
        max_age=REFRESH_TOKEN_TTL,
        path=config.refresh_path,
        httponly=True,
        secure=cookies_secure,
        samesite=config.refresh_same_site,
    )
    response.set_cookie(
        key=config.csrf_name,
        value=csrf_token,
        max_age=CSRF_TOKEN_TTL,
        path=config.csrf_path,
        httponly=False,  # double-submit pattern needs JS read access
        secure=cookies_secure,
        samesite=config.csrf_same_site,
    )


def clear_session_cookies(
    response: _CookieResponse,
    *,
    config: CookieConfig = USER_COOKIE_CONFIG,
) -> None:
    """Remove the three session cookies — used on logout."""
    response.delete_cookie(config.access_name, path=config.access_path)
    response.delete_cookie(config.refresh_name, path=config.refresh_path)
    response.delete_cookie(config.csrf_name, path=config.csrf_path)


def set_admin_pre_totp_cookie(
    response: _CookieResponse,
    *,
    token: str,
    cookies_secure: bool = True,
) -> None:
    """Path-restricted ``admin_pre_totp`` cookie per AC-phase1-admin-002a-01.

    Only sent on the TOTP verify endpoint, never on the user-side surface.
    """
    response.set_cookie(
        key=ADMIN_PRE_TOTP_COOKIE_NAME,
        value=token,
        max_age=ADMIN_PRE_TOTP_TTL,
        path=ADMIN_PRE_TOTP_COOKIE_PATH,
        httponly=True,
        secure=cookies_secure,
        samesite=SAME_SITE_LAX,
    )


def clear_admin_pre_totp_cookie(response: _CookieResponse) -> None:
    response.delete_cookie(ADMIN_PRE_TOTP_COOKIE_NAME, path=ADMIN_PRE_TOTP_COOKIE_PATH)


__all__ = [
    "ACCESS_COOKIE_NAME",
    "ACCESS_TOKEN_TTL",
    "ADMIN_ACCESS_COOKIE_NAME",
    "ADMIN_BASE_PATH",
    "ADMIN_COOKIE_CONFIG",
    "ADMIN_CSRF_COOKIE_NAME",
    "ADMIN_PRE_TOTP_COOKIE_NAME",
    "ADMIN_PRE_TOTP_COOKIE_PATH",
    "ADMIN_PRE_TOTP_TTL",
    "ADMIN_REFRESH_COOKIE_NAME",
    "ADMIN_REFRESH_COOKIE_PATH",
    "CSRF_COOKIE_NAME",
    "CSRF_TOKEN_TTL",
    "CookieConfig",
    "REFRESH_COOKIE_NAME",
    "REFRESH_COOKIE_PATH",
    "REFRESH_TOKEN_TTL",
    "ROOT_PATH",
    "SAME_SITE_LAX",
    "SAME_SITE_STRICT",
    "USER_COOKIE_CONFIG",
    "clear_admin_pre_totp_cookie",
    "clear_session_cookies",
    "set_admin_pre_totp_cookie",
    "set_session_cookies",
]
