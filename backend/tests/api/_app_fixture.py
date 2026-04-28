"""Build a FastAPI app for contract tests with composition functions
overridden to use the in-memory fakes.

Tests that exercise the full request → use-case → response loop without
spinning up Postgres / Redis use this builder. Adapter-level tests that
hit a real Redis still live under tests/identity/infra/ and use
testcontainers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Request

from tests.identity.fakes.fake_access_token_cache import FakeAccessTokenCache
from tests.identity.fakes.fake_backup_code_service import (
    FakeBackupCodeService,
)
from tests.identity.fakes.fake_email_sender import FakeEmailSender
from tests.identity.fakes.fake_encryptor import FakeTotpEncryptor
from tests.identity.fakes.fake_magic_link_token_generator import (
    DeterministicMagicLinkTokenGenerator,
)
from tests.identity.fakes.fake_password_hasher import FakePasswordHasher
from tests.identity.fakes.fake_pre_totp_cache import FakePreTotpTokenCache
from tests.identity.fakes.fake_repositories import (
    InMemoryMagicLinkRepository,
    InMemorySessionRepository,
    InMemoryTotpSecretRepository,
    InMemoryUserRepository,
)
from tests.identity.fakes.fake_token_generator import DeterministicTokenGenerator
from tests.identity.fakes.fake_totp_checker import (
    FakeTotpCodeChecker,
)
from tests.identity.fakes.fake_uow import FakeUnitOfWork
from vaultchain.identity.application.admin_login import AdminLogin
from vaultchain.identity.application.admin_totp_verify import AdminTotpVerify
from vaultchain.identity.application.consume_magic_link import ConsumeMagicLink
from vaultchain.identity.application.create_session import CreateSession
from vaultchain.identity.application.enroll_totp import EnrollTotp
from vaultchain.identity.application.refresh_session import RefreshSession
from vaultchain.identity.application.regenerate_backup_codes import RegenerateBackupCodes
from vaultchain.identity.application.request_magic_link import RequestMagicLink
from vaultchain.identity.application.revoke_session import RevokeSession
from vaultchain.identity.application.verify_totp import VerifyTotp
from vaultchain.identity.delivery.composition import (
    get_access_cache,
    get_admin_login,
    get_admin_totp_verify,
    get_consume_magic_link,
    get_create_session,
    get_current_admin,
    get_current_user,
    get_enroll_totp,
    get_password_hasher,
    get_pre_totp_cache,
    get_refresh_session,
    get_regenerate_backup_codes,
    get_request_magic_link,
    get_revoke_session,
    get_totp_repo_factory,
    get_uow_factory,
    get_verify_totp,
)
from vaultchain.identity.delivery.dependencies.admin_user import GetCurrentAdmin
from vaultchain.identity.delivery.dependencies.current_user import (
    GetCurrentUser,
)
from vaultchain.identity.delivery.routes import build_admin_router, build_identity_router
from vaultchain.shared.delivery import (
    RequestIdMiddleware,
    register_error_handlers,
)


class AppState:
    """Simple bag holding the in-memory state shared across requests."""

    def __init__(self) -> None:
        self.users = InMemoryUserRepository()
        self.sessions = InMemorySessionRepository()
        self.magic_links = InMemoryMagicLinkRepository()
        self.totp_secrets = InMemoryTotpSecretRepository()
        self.access_cache = FakeAccessTokenCache()
        self.pre_totp_cache = FakePreTotpTokenCache()
        self.email_sender = FakeEmailSender()
        self.token_gen = DeterministicTokenGenerator()
        self.magic_link_gen = DeterministicMagicLinkTokenGenerator()
        self.totp_checker = FakeTotpCodeChecker(accepted_codes=("123456",))
        self.totp_encryptor = FakeTotpEncryptor()
        self.backup_codes = FakeBackupCodeService()
        self.password_hasher = FakePasswordHasher()


def _identity_overrides(state: AppState) -> dict[Callable[..., Any], Callable[..., Any]]:
    def _user_repo_factory(_session: Any) -> Any:
        return state.users

    def _session_repo_factory(_session: Any) -> Any:
        return state.sessions

    def _magic_link_repo_factory(_session: Any) -> Any:
        return state.magic_links

    def _totp_repo_factory(_session: Any) -> Any:
        return state.totp_secrets

    def _uow_factory_resolver() -> Callable[[], FakeUnitOfWork]:
        return lambda: FakeUnitOfWork()

    return {
        get_uow_factory: _uow_factory_resolver,
        get_totp_repo_factory: lambda: _totp_repo_factory,
        get_access_cache: lambda: state.access_cache,
        get_pre_totp_cache: lambda: state.pre_totp_cache,
        get_request_magic_link: lambda: RequestMagicLink(
            uow_factory=lambda: FakeUnitOfWork(),
            users=_user_repo_factory,
            magic_links=_magic_link_repo_factory,
            emails=state.email_sender,
            token_gen=state.magic_link_gen,
        ),
        get_consume_magic_link: lambda: ConsumeMagicLink(
            uow_factory=lambda: FakeUnitOfWork(),
            users=_user_repo_factory,
            magic_links=_magic_link_repo_factory,
            totp_secrets=_totp_repo_factory,
        ),
        get_create_session: lambda: CreateSession(
            uow_factory=lambda: FakeUnitOfWork(),
            sessions=_session_repo_factory,
            cache=state.access_cache,
            token_gen=state.token_gen,
        ),
        get_refresh_session: lambda: RefreshSession(
            uow_factory=lambda: FakeUnitOfWork(),
            sessions=_session_repo_factory,
            cache=state.access_cache,
            token_gen=state.token_gen,
        ),
        get_revoke_session: lambda: RevokeSession(
            uow_factory=lambda: FakeUnitOfWork(),
            sessions=_session_repo_factory,
            cache=state.access_cache,
        ),
        get_enroll_totp: lambda: EnrollTotp(
            uow_factory=lambda: FakeUnitOfWork(),
            users=_user_repo_factory,
            totps=_totp_repo_factory,
            encryptor=state.totp_encryptor,
            code_checker=state.totp_checker,
            backup_codes=state.backup_codes,
        ),
        get_verify_totp: lambda: VerifyTotp(
            uow_factory=lambda: FakeUnitOfWork(),
            users=_user_repo_factory,
            totps=_totp_repo_factory,
            encryptor=state.totp_encryptor,
            code_checker=state.totp_checker,
            backup_codes=state.backup_codes,
        ),
        get_regenerate_backup_codes: lambda: RegenerateBackupCodes(
            uow_factory=lambda: FakeUnitOfWork(),
            users=_user_repo_factory,
            totps=_totp_repo_factory,
            backup_codes=state.backup_codes,
        ),
        get_current_user: _build_current_user_resolver(state, _user_repo_factory),
        get_password_hasher: lambda: state.password_hasher,
        get_admin_login: lambda: AdminLogin(
            uow_factory=lambda: FakeUnitOfWork(),
            users=_user_repo_factory,
            password_hasher=state.password_hasher,
        ),
        get_admin_totp_verify: lambda: AdminTotpVerify(
            uow_factory=lambda: FakeUnitOfWork(),
            users=_user_repo_factory,
            verify_totp=VerifyTotp(
                uow_factory=lambda: FakeUnitOfWork(),
                users=_user_repo_factory,
                totps=_totp_repo_factory,
                encryptor=state.totp_encryptor,
                code_checker=state.totp_checker,
                backup_codes=state.backup_codes,
            ),
            create_session=CreateSession(
                uow_factory=lambda: FakeUnitOfWork(),
                sessions=_session_repo_factory,
                cache=state.access_cache,
                token_gen=state.token_gen,
            ),
        ),
        get_current_admin: _build_current_admin_resolver(state, _user_repo_factory),
    }


def _build_current_admin_resolver(
    state: AppState, user_repo_factory: Callable[[Any], Any]
) -> Callable[[Request], Any]:
    """Mirror ``_build_current_user_resolver`` for the admin scope."""
    gca = GetCurrentAdmin(
        cache=state.access_cache,
        uow_factory=lambda: FakeUnitOfWork(),
        users=user_repo_factory,
    )

    async def _resolver(request: Request) -> Any:
        return await gca(request)

    return _resolver


def _build_current_user_resolver(
    state: AppState, user_repo_factory: Callable[[Any], Any]
) -> Callable[[Request], Any]:
    """Return an async resolver that calls GetCurrentUser per request,
    matching FastAPI's expectation that a dependency returns the value
    (UserContext) — not a callable that produces the value.
    """
    gcu = GetCurrentUser(
        cache=state.access_cache,
        uow_factory=lambda: FakeUnitOfWork(),
        users=user_repo_factory,
    )

    async def _resolver(request: Request) -> Any:
        return await gcu(request)

    return _resolver


def build_test_app(
    state: AppState | None = None,
    *,
    include_admin: bool = False,
) -> tuple[FastAPI, AppState]:
    """Compose an app whose composition resolvers are patched to fakes.

    The returned `TestState` lets tests poke the in-memory repos to
    verify side effects. ``include_admin=True`` mounts the
    ``/admin/api/v1`` router for admin contract tests.
    """
    state = state or AppState()
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    app.include_router(build_identity_router())
    if include_admin:
        app.include_router(build_admin_router())
    overrides = _identity_overrides(state)
    for original, replacement in overrides.items():
        app.dependency_overrides[original] = replacement
    return app, state


# Re-exported for the few tests that build user_id directly.
def make_user_id() -> UUID:
    from uuid import uuid4

    return uuid4()


__all__ = ["AppState", "build_test_app", "make_user_id"]
