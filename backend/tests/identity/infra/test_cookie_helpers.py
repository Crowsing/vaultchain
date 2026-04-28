"""Cookie-helper tests — AC-phase1-identity-004-10.

Uses a recorder that captures each `set_cookie` call so we can assert the
exact attributes (httponly, secure, samesite, path, max_age) on each of
the three cookies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from vaultchain.identity.infra.tokens.cookies import (
    ACCESS_COOKIE_NAME,
    ACCESS_TOKEN_TTL,
    CSRF_COOKIE_NAME,
    CSRF_TOKEN_TTL,
    REFRESH_COOKIE_NAME,
    REFRESH_COOKIE_PATH,
    REFRESH_TOKEN_TTL,
    ROOT_PATH,
    SAME_SITE_LAX,
    clear_session_cookies,
    set_session_cookies,
)


@dataclass
class _RecorderResponse:
    set_calls: list[dict[str, Any]] = field(default_factory=list)
    deleted: list[dict[str, Any]] = field(default_factory=list)

    def set_cookie(
        self,
        key: str,
        value: str,
        *,
        max_age: int,
        path: str,
        httponly: bool,
        secure: bool,
        samesite: str,
    ) -> None:
        self.set_calls.append(
            {
                "key": key,
                "value": value,
                "max_age": max_age,
                "path": path,
                "httponly": httponly,
                "secure": secure,
                "samesite": samesite,
            }
        )

    def delete_cookie(self, key: str, *, path: str) -> None:
        self.deleted.append({"key": key, "path": path})


def _by_name(calls: list[dict[str, Any]], name: str) -> dict[str, Any]:
    matching = [c for c in calls if c["key"] == name]
    assert len(matching) == 1, f"expected exactly one {name} cookie call, got {len(matching)}"
    return matching[0]


def test_ac_10_access_cookie_attributes() -> None:
    resp = _RecorderResponse()
    set_session_cookies(
        resp,
        access_token="vc_at_aaa",
        refresh_token="vc_rt_bbb",
        csrf_token="vc_csrf_ccc",
    )
    cookie = _by_name(resp.set_calls, ACCESS_COOKIE_NAME)
    assert cookie["value"] == "vc_at_aaa"
    assert cookie["httponly"] is True
    assert cookie["secure"] is True
    assert cookie["samesite"] == SAME_SITE_LAX
    assert cookie["path"] == ROOT_PATH
    assert cookie["max_age"] == ACCESS_TOKEN_TTL == 900


def test_ac_10_refresh_cookie_attributes_path_restricted() -> None:
    resp = _RecorderResponse()
    set_session_cookies(
        resp,
        access_token="x",
        refresh_token="vc_rt_secret",
        csrf_token="y",
    )
    cookie = _by_name(resp.set_calls, REFRESH_COOKIE_NAME)
    assert cookie["value"] == "vc_rt_secret"
    assert cookie["httponly"] is True
    assert cookie["secure"] is True
    assert cookie["samesite"] == SAME_SITE_LAX
    assert cookie["path"] == REFRESH_COOKIE_PATH == "/api/v1/auth/refresh"
    assert cookie["max_age"] == REFRESH_TOKEN_TTL == 2592000


def test_ac_10_csrf_cookie_is_not_http_only() -> None:
    resp = _RecorderResponse()
    set_session_cookies(
        resp,
        access_token="x",
        refresh_token="y",
        csrf_token="vc_csrf_token",
    )
    cookie = _by_name(resp.set_calls, CSRF_COOKIE_NAME)
    assert cookie["value"] == "vc_csrf_token"
    assert cookie["httponly"] is False  # JS reads it for double-submit
    assert cookie["secure"] is True
    assert cookie["samesite"] == SAME_SITE_LAX
    assert cookie["path"] == ROOT_PATH
    assert cookie["max_age"] == CSRF_TOKEN_TTL == 900


def test_ac_10_cookies_secure_override_for_local_dev() -> None:
    resp = _RecorderResponse()
    set_session_cookies(
        resp,
        access_token="x",
        refresh_token="y",
        csrf_token="z",
        cookies_secure=False,
    )
    for cookie in resp.set_calls:
        assert cookie["secure"] is False


def test_clear_session_cookies_deletes_three_with_correct_paths() -> None:
    resp = _RecorderResponse()
    clear_session_cookies(resp)
    paths_by_key = {d["key"]: d["path"] for d in resp.deleted}
    assert paths_by_key == {
        ACCESS_COOKIE_NAME: ROOT_PATH,
        REFRESH_COOKIE_NAME: REFRESH_COOKIE_PATH,
        CSRF_COOKIE_NAME: ROOT_PATH,
    }


# Touching pytest at module scope keeps tooling from stripping the import
# if the file shrinks during refactors.
_ = pytest
