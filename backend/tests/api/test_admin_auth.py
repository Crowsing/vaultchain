"""End-to-end contract tests for the admin auth API — phase1-admin-002a.

Walks the happy-path admin login + TOTP verify + /me + logout flow via
FastAPI TestClient. Covers AC-01..AC-05 plus the AC-Done-Definition
"admin filtered out of public OpenAPI" assertion.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.api._app_fixture import AppState, build_test_app
from tests.identity.fakes.fake_repositories import InMemoryUserRepository
from vaultchain.identity.domain.aggregates import TotpSecret, User
from vaultchain.identity.domain.value_objects import Email
from vaultchain.identity.infra.tokens.cookies import (
    ADMIN_ACCESS_COOKIE_NAME,
    ADMIN_CSRF_COOKIE_NAME,
    ADMIN_PRE_TOTP_COOKIE_NAME,
    ADMIN_REFRESH_COOKIE_NAME,
)


@pytest.fixture
def state() -> AppState:
    return AppState()


@pytest.fixture
def admin(state: AppState) -> User:
    """Seed an admin row + TOTP secret in the in-memory state."""
    admin = User.seed_admin(
        email="admin@vaultchain.io",
        email_hash=Email("admin@vaultchain.io").hash_blake2b(),
        password_hash=state.password_hasher.hash("strong-passphrase-123"),
        full_name="Demo Admin",
        role="admin",
    )
    _seed_user(state.users, admin)
    state.totp_secrets.seed(
        TotpSecret.enroll(
            user_id=admin.id,
            secret_plain=b"JBSWY3DPEHPK3PXP",
            backup_codes_hashed=[],
            encryptor=state.totp_encryptor,
        )
    )
    return admin


def _seed_user(repo: InMemoryUserRepository, user: User) -> None:
    repo.seed(user)


@pytest.fixture
def client(state: AppState) -> Iterator[TestClient]:
    app, _ = build_test_app(state, include_admin=True)
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def test_ac_01_login_sets_pre_totp_cookie(client: TestClient, state: AppState, admin: User) -> None:
    r = client.post(
        "/admin/api/v1/auth/login",
        json={"email": admin.email, "password": "strong-passphrase-123"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"pre_totp_required": True}
    assert ADMIN_PRE_TOTP_COOKIE_NAME in r.cookies
    # Token landed in the pre-TOTP cache.
    assert len(state.pre_totp_cache._store) == 1


def test_ac_02_wrong_password_returns_invalid_credentials(client: TestClient, admin: User) -> None:
    r = client.post(
        "/admin/api/v1/auth/login",
        json={"email": admin.email, "password": "definitely-wrong-12!"},
    )
    assert r.status_code == 401
    body = r.json()
    assert body["error"]["code"] == "identity.invalid_credentials"
    assert "request_id" in body["error"]


def test_ac_02_lockout_after_threshold(client: TestClient, admin: User) -> None:
    for _ in range(5):
        r = client.post(
            "/admin/api/v1/auth/login",
            json={"email": admin.email, "password": "definitely-wrong-12!"},
        )
        assert r.status_code == 401

    r = client.post(
        "/admin/api/v1/auth/login",
        json={"email": admin.email, "password": "strong-passphrase-123"},
    )
    assert r.status_code == 403
    body = r.json()
    assert body["error"]["code"] == "identity.user_locked"


def test_ac_03_totp_verify_mints_admin_session(client: TestClient, admin: User) -> None:
    login = client.post(
        "/admin/api/v1/auth/login",
        json={"email": admin.email, "password": "strong-passphrase-123"},
    )
    assert login.status_code == 200

    verify = client.post(
        "/admin/api/v1/auth/totp/verify",
        json={"code": "123456"},
    )
    assert verify.status_code == 200, verify.text
    body = verify.json()
    assert body["user"]["actor_type"] == "admin"
    assert body["user"]["email"] == admin.email

    cookies = verify.cookies
    assert ADMIN_ACCESS_COOKIE_NAME in cookies
    assert ADMIN_REFRESH_COOKIE_NAME in cookies
    assert ADMIN_CSRF_COOKIE_NAME in cookies


def test_ac_04_admin_endpoint_without_session_returns_session_required(
    client: TestClient,
) -> None:
    # /me without a session — middleware rejects with 401 + session_required.
    r = client.get("/admin/api/v1/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "identity.session_required"


async def test_ac_04_user_token_at_admin_endpoint_returns_admin_required(
    client: TestClient, state: AppState
) -> None:
    """A user-actor session presented at an admin endpoint → 403 admin_required.

    Simulated by injecting a user-scoped CachedAccessToken into the cache
    and supplying its raw token via the ``admin_at`` cookie.
    """
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from vaultchain.identity.domain.ports import CachedAccessToken
    from vaultchain.identity.infra.tokens.hashing import sha256_hex

    raw_token = "vc_at_TEST_user_session"
    user_id = uuid4()
    state.users.seed(
        User.signup(email="user@example.com", email_hash=b"\x00" * 32, user_id=user_id)
    )
    cached = CachedAccessToken(
        user_id=user_id,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
        scopes=("user",),
        session_id=uuid4(),
    )
    await state.access_cache.set(sha256_hex(raw_token), cached)

    client.cookies.set(ADMIN_ACCESS_COOKIE_NAME, raw_token)
    r = client.get("/admin/api/v1/auth/me")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "identity.admin_required"


def test_ac_05_admin_me_returns_profile(client: TestClient, admin: User) -> None:
    client.post(
        "/admin/api/v1/auth/login",
        json={"email": admin.email, "password": "strong-passphrase-123"},
    )
    client.post("/admin/api/v1/auth/totp/verify", json={"code": "123456"})

    r = client.get("/admin/api/v1/auth/me")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == admin.email
    assert body["role"] == "admin"
    assert body["full_name"] == "Demo Admin"


def test_admin_routes_filtered_from_public_openapi(client: TestClient) -> None:
    r = client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    paths = schema.get("paths", {})
    for path in paths:
        assert not path.startswith("/admin/"), f"Admin route leaked into public OpenAPI: {path}"
