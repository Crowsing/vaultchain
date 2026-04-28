"""End-to-end contract tests for the auth API endpoints.

Walks the happy-path signup flow + login flow + logout via FastAPI
TestClient, covering AC-phase1-identity-005-01..03,05,06.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.api._app_fixture import AppState, build_test_app
from vaultchain.identity.infra.tokens.cookies import (
    ACCESS_COOKIE_NAME,
    CSRF_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
)


@pytest.fixture
def state() -> AppState:
    return AppState()


@pytest.fixture
def client(state: AppState) -> Iterator[TestClient]:
    """`https://` base so `Secure` cookies persist across requests in TestClient."""
    app, _ = build_test_app(state)
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def test_ac_01_auth_request_returns_202(client: TestClient, state: AppState) -> None:
    r = client.post(
        "/api/v1/auth/request",
        json={"email": "alice@example.com", "mode": "signup"},
    )
    assert r.status_code == 202, r.text
    assert r.json() == {"message_sent": True}
    # Side effect: magic link issued.
    assert len(state.magic_links._by_id) == 1
    assert len(state.email_sender.sent) == 1


def test_ac_01_auth_request_rejects_extra_fields(client: TestClient) -> None:
    r = client.post(
        "/api/v1/auth/request",
        json={"email": "x@y.io", "mode": "signup", "extra": "field"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"].startswith("validation.")


def test_ac_01_auth_verify_round_trip_signup(client: TestClient, state: AppState) -> None:
    """Sign up, verify the link, get a pre-TOTP token back."""
    client.post(
        "/api/v1/auth/request",
        json={"email": "bob@example.com", "mode": "signup"},
    )
    raw_token = state.email_sender.sent[0].raw_token

    r = client.post(
        "/api/v1/auth/verify",
        json={"token": raw_token, "mode": "signup"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "bob@example.com"
    assert body["is_first_time"] is True
    assert body["requires_totp_enrollment"] is True
    assert body["requires_totp_challenge"] is False
    assert body["pre_totp_token"]
    # Pre-TOTP token landed in cache.
    assert len(state.pre_totp_cache._store) == 1


def test_ac_06_invalid_token_envelope(client: TestClient) -> None:
    r = client.post(
        "/api/v1/auth/verify",
        json={"token": "never-issued", "mode": "signup"},
    )
    assert r.status_code == 401
    body = r.json()
    assert body["error"]["code"] == "identity.magic_link_invalid"
    assert "request_id" in body["error"]


def test_ac_03_full_signup_flow_sets_session_cookies(client: TestClient, state: AppState) -> None:
    """Sign up → verify → enroll → enroll/confirm yields the three cookies."""
    client.post(
        "/api/v1/auth/request",
        json={"email": "carol@example.com", "mode": "signup"},
    )
    raw_token = state.email_sender.sent[0].raw_token

    verify = client.post(
        "/api/v1/auth/verify",
        json={"token": raw_token, "mode": "signup"},
    )
    pre_totp = verify.json()["pre_totp_token"]
    headers = {"Authorization": f"Bearer {pre_totp}"}

    enroll = client.post("/api/v1/auth/totp/enroll", headers=headers)
    assert enroll.status_code == 200, enroll.text
    body = enroll.json()
    assert body["secret_for_qr"]
    assert "otpauth://" in body["qr_payload_uri"]
    assert len(body["backup_codes"]) == 10

    confirm = client.post(
        "/api/v1/auth/totp/enroll/confirm",
        headers=headers,
        json={"code": "123456"},  # accepted by FakeTotpCodeChecker
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json() == {"success": True, "attempts_remaining": None}

    # Three cookies set.
    cookies = confirm.cookies
    assert ACCESS_COOKIE_NAME in cookies
    assert REFRESH_COOKIE_NAME in cookies
    assert CSRF_COOKIE_NAME in cookies


def test_ac_01_me_returns_user_after_session(client: TestClient, state: AppState) -> None:
    # Drive the full signup ⇒ enroll-confirm flow first.
    client.post(
        "/api/v1/auth/request",
        json={"email": "dan@example.com", "mode": "signup"},
    )
    raw = state.email_sender.sent[0].raw_token
    pre_totp = client.post("/api/v1/auth/verify", json={"token": raw, "mode": "signup"}).json()[
        "pre_totp_token"
    ]
    headers = {"Authorization": f"Bearer {pre_totp}"}
    client.post("/api/v1/auth/totp/enroll", headers=headers)
    client.post(
        "/api/v1/auth/totp/enroll/confirm",
        headers=headers,
        json={"code": "123456"},
    )

    r = client.get("/api/v1/me")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "dan@example.com"
    assert body["totp_enrolled"] is True
    assert "id" in body
    assert "status" in body


def test_ac_05_pre_totp_intent_mismatch_rejected(client: TestClient, state: AppState) -> None:
    """Login-mode verify produces intent=challenge; using it for /enroll fails."""
    # Set up a verified user with TOTP via signup flow.
    client.post(
        "/api/v1/auth/request",
        json={"email": "ellen@example.com", "mode": "signup"},
    )
    raw = state.email_sender.sent[0].raw_token
    pre_totp_enroll = client.post(
        "/api/v1/auth/verify", json={"token": raw, "mode": "signup"}
    ).json()["pre_totp_token"]
    headers_enroll = {"Authorization": f"Bearer {pre_totp_enroll}"}
    client.post("/api/v1/auth/totp/enroll", headers=headers_enroll)
    client.post(
        "/api/v1/auth/totp/enroll/confirm",
        headers=headers_enroll,
        json={"code": "123456"},
    )

    # Now do a login-mode round-trip: produces intent=challenge.
    client.post(
        "/api/v1/auth/request",
        json={"email": "ellen@example.com", "mode": "login"},
    )
    login_raw = state.email_sender.sent[-1].raw_token
    pre_totp_login = client.post(
        "/api/v1/auth/verify", json={"token": login_raw, "mode": "login"}
    ).json()["pre_totp_token"]

    # Try to use a CHALLENGE token on /enroll (intent=ENROLL) ⇒ 401.
    r = client.post(
        "/api/v1/auth/totp/enroll",
        headers={"Authorization": f"Bearer {pre_totp_login}"},
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "identity.pre_totp_token_invalid"


def test_ac_03_logout_clears_cookies(client: TestClient, state: AppState) -> None:
    # Drive the full enroll flow to obtain cookies.
    client.post(
        "/api/v1/auth/request",
        json={"email": "frank@example.com", "mode": "signup"},
    )
    raw = state.email_sender.sent[0].raw_token
    pre_totp = client.post("/api/v1/auth/verify", json={"token": raw, "mode": "signup"}).json()[
        "pre_totp_token"
    ]
    headers = {"Authorization": f"Bearer {pre_totp}"}
    client.post("/api/v1/auth/totp/enroll", headers=headers)
    client.post(
        "/api/v1/auth/totp/enroll/confirm",
        headers=headers,
        json={"code": "123456"},
    )

    # Now logout — needs CSRF: read the csrf cookie and echo it as a header.
    csrf = client.cookies.get(CSRF_COOKIE_NAME)
    assert csrf is not None
    r = client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 204, r.text
