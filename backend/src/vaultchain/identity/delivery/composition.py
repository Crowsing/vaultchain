"""Composition root for the identity delivery layer.

These dependency-resolver functions (FastAPI ``Depends`` targets) are
the single point where concrete adapters are wired into use cases.
Tests use ``app.dependency_overrides[...]`` to swap in fakes — see
the contract tests under ``tests/api/``.

Rules:
- One factory per use case so a test can override a single piece.
- All factories return new use-case instances per request — they're
  cheap to construct and stateless once built.
- Adapters whose construction is expensive (Redis client, sessionmaker)
  are cached at app startup time on ``app.state``; the resolvers below
  read from there.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from vaultchain.config import Settings, get_settings
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
from vaultchain.identity.delivery.dependencies.admin_user import (
    AdminContext,
    GetCurrentAdmin,
)
from vaultchain.identity.delivery.dependencies.csrf import CsrfGuard
from vaultchain.identity.delivery.dependencies.current_user import GetCurrentUser
from vaultchain.identity.domain.ports import (
    AccessTokenCache,
    EmailSender,
    MagicLinkTokenGenerator,
    PasswordHasher,
    PreTotpTokenCache,
    RefreshTokenGenerator,
)
from vaultchain.identity.infra.bcrypt_password_hasher import BcryptPasswordHasher
from vaultchain.identity.infra.email.console import ConsoleEmailSender
from vaultchain.identity.infra.repositories import (
    SqlAlchemyMagicLinkRepository,
    SqlAlchemySessionRepository,
    SqlAlchemyTotpSecretRepository,
    SqlAlchemyUserRepository,
)
from vaultchain.identity.infra.tokens.generator import SecretsRefreshTokenGenerator
from vaultchain.identity.infra.tokens.magic_link_generator import (
    SecretsMagicLinkTokenGenerator,
)
from vaultchain.identity.infra.tokens.pre_totp_cache import RedisPreTotpTokenCache
from vaultchain.identity.infra.tokens.redis_cache import RedisAccessTokenCache
from vaultchain.identity.infra.totp.backup_codes import Argon2BackupCodeService
from vaultchain.identity.infra.totp.pyotp_checker import PyOtpCodeChecker
from vaultchain.identity.infra.totp_encryptor import StaticKeyTotpEncryptor
from vaultchain.shared.infra.unit_of_work import SqlAlchemyUnitOfWork
from vaultchain.shared.unit_of_work import AbstractUnitOfWork


def install_identity_dependencies(app: FastAPI, settings: Settings) -> None:
    """Build the concrete adapters once and stash them on ``app.state``.

    Called from the FastAPI app factory; the lifespan handler closes
    the Redis clients on shutdown.
    """
    engine = create_async_engine(settings.database_url, future=True)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    access_cache = RedisAccessTokenCache.from_url(settings.redis_url)
    pre_totp_cache = RedisPreTotpTokenCache.from_url(settings.redis_url)

    app.state.identity_engine = engine
    app.state.identity_sessionmaker = sessionmaker
    app.state.identity_access_cache = access_cache
    app.state.identity_pre_totp_cache = pre_totp_cache
    app.state.identity_email_sender = ConsoleEmailSender(frontend_url=settings.frontend_url)
    app.state.identity_token_gen = SecretsRefreshTokenGenerator()
    app.state.identity_magic_link_gen = SecretsMagicLinkTokenGenerator()
    app.state.identity_totp_encryptor = StaticKeyTotpEncryptor(
        key=settings.secret_key.get_secret_value().encode("utf-8")[:32].ljust(32, b"\x00")
    )
    app.state.identity_totp_checker = PyOtpCodeChecker()
    app.state.identity_backup_codes = Argon2BackupCodeService()
    app.state.identity_password_hasher = BcryptPasswordHasher()


async def shutdown_identity_dependencies(app: FastAPI) -> None:
    """Close Redis pools + engine on app shutdown."""
    cache = getattr(app.state, "identity_access_cache", None)
    if cache is not None:
        await cache.aclose()
    pre_totp = getattr(app.state, "identity_pre_totp_cache", None)
    if pre_totp is not None:
        await pre_totp.aclose()
    engine = getattr(app.state, "identity_engine", None)
    if engine is not None:
        await engine.dispose()


# --------- Resolver helpers (read from app.state when available) ---------


def _state(request: Request, name: str) -> Any:
    return getattr(request.app.state, name)


def get_uow_factory(request: Request) -> Callable[[], AbstractUnitOfWork]:
    sessionmaker = _state(request, "identity_sessionmaker")
    return lambda: SqlAlchemyUnitOfWork(sessionmaker)


def get_user_repo_factory(_request: Request) -> Callable[[Any], Any]:
    return lambda session: SqlAlchemyUserRepository(session)


def get_session_repo_factory(_request: Request) -> Callable[[Any], Any]:
    return lambda session: SqlAlchemySessionRepository(session)


def get_magic_link_repo_factory(_request: Request) -> Callable[[Any], Any]:
    return lambda session: SqlAlchemyMagicLinkRepository(session)


def get_totp_repo_factory(_request: Request) -> Callable[[Any], Any]:
    return lambda session: SqlAlchemyTotpSecretRepository(session)


def get_access_cache(request: Request) -> AccessTokenCache:
    return cast(AccessTokenCache, _state(request, "identity_access_cache"))


def get_pre_totp_cache(request: Request) -> PreTotpTokenCache:
    return cast(PreTotpTokenCache, _state(request, "identity_pre_totp_cache"))


def get_email_sender(request: Request) -> EmailSender:
    return cast(EmailSender, _state(request, "identity_email_sender"))


def get_token_gen(request: Request) -> RefreshTokenGenerator:
    return cast(RefreshTokenGenerator, _state(request, "identity_token_gen"))


def get_magic_link_token_gen(request: Request) -> MagicLinkTokenGenerator:
    return cast(MagicLinkTokenGenerator, _state(request, "identity_magic_link_gen"))


# --------------------------- Use case resolvers --------------------------


def get_request_magic_link(request: Request) -> RequestMagicLink:
    return RequestMagicLink(
        uow_factory=get_uow_factory(request),
        users=get_user_repo_factory(request),
        magic_links=get_magic_link_repo_factory(request),
        emails=get_email_sender(request),
        token_gen=get_magic_link_token_gen(request),
    )


def get_consume_magic_link(request: Request) -> ConsumeMagicLink:
    return ConsumeMagicLink(
        uow_factory=get_uow_factory(request),
        users=get_user_repo_factory(request),
        magic_links=get_magic_link_repo_factory(request),
        totp_secrets=get_totp_repo_factory(request),
    )


def get_create_session(request: Request) -> CreateSession:
    return CreateSession(
        uow_factory=get_uow_factory(request),
        sessions=get_session_repo_factory(request),
        cache=get_access_cache(request),
        token_gen=get_token_gen(request),
    )


def get_refresh_session(request: Request) -> RefreshSession:
    return RefreshSession(
        uow_factory=get_uow_factory(request),
        sessions=get_session_repo_factory(request),
        cache=get_access_cache(request),
        token_gen=get_token_gen(request),
    )


def get_revoke_session(request: Request) -> RevokeSession:
    return RevokeSession(
        uow_factory=get_uow_factory(request),
        sessions=get_session_repo_factory(request),
        cache=get_access_cache(request),
    )


def get_enroll_totp(request: Request) -> EnrollTotp:
    return EnrollTotp(
        uow_factory=get_uow_factory(request),
        users=get_user_repo_factory(request),
        totps=get_totp_repo_factory(request),
        encryptor=_state(request, "identity_totp_encryptor"),
        code_checker=_state(request, "identity_totp_checker"),
        backup_codes=_state(request, "identity_backup_codes"),
    )


def get_verify_totp(request: Request) -> VerifyTotp:
    return VerifyTotp(
        uow_factory=get_uow_factory(request),
        users=get_user_repo_factory(request),
        totps=get_totp_repo_factory(request),
        encryptor=_state(request, "identity_totp_encryptor"),
        code_checker=_state(request, "identity_totp_checker"),
        backup_codes=_state(request, "identity_backup_codes"),
    )


def get_regenerate_backup_codes(request: Request) -> RegenerateBackupCodes:
    return RegenerateBackupCodes(
        uow_factory=get_uow_factory(request),
        users=get_user_repo_factory(request),
        totps=get_totp_repo_factory(request),
        backup_codes=_state(request, "identity_backup_codes"),
    )


async def get_current_user(request: Request) -> Any:
    """Resolve the current user via the GetCurrentUser callable.

    Direct dispatch keeps routes' Depends(get_current_user) returning a
    `UserContext` rather than a callable wrapper FastAPI would not
    auto-invoke.
    """
    gcu = GetCurrentUser(
        cache=get_access_cache(request),
        uow_factory=get_uow_factory(request),
        users=get_user_repo_factory(request),
    )
    return await gcu(request)


async def get_current_admin(request: Request) -> AdminContext:
    """Resolve the current admin via the GetCurrentAdmin callable."""
    gca = GetCurrentAdmin(
        cache=get_access_cache(request),
        uow_factory=get_uow_factory(request),
        users=get_user_repo_factory(request),
    )
    return await gca(request)


def get_password_hasher(request: Request) -> PasswordHasher:
    return cast(PasswordHasher, _state(request, "identity_password_hasher"))


def get_admin_login(request: Request) -> AdminLogin:
    return AdminLogin(
        uow_factory=get_uow_factory(request),
        users=get_user_repo_factory(request),
        password_hasher=get_password_hasher(request),
    )


def get_admin_totp_verify(request: Request) -> AdminTotpVerify:
    return AdminTotpVerify(
        uow_factory=get_uow_factory(request),
        users=get_user_repo_factory(request),
        verify_totp=get_verify_totp(request),
        create_session=get_create_session(request),
    )


def get_csrf_guard(_request: Request) -> CsrfGuard:
    return CsrfGuard()


# `get_settings` is also re-exported for routes that read configuration
# directly (e.g. cookie helpers reading the cookie domain).
def get_app_settings(_request: Request) -> Settings:
    return get_settings()


__all__ = [
    "get_access_cache",
    "get_admin_login",
    "get_admin_totp_verify",
    "get_app_settings",
    "get_consume_magic_link",
    "get_create_session",
    "get_csrf_guard",
    "get_current_admin",
    "get_current_user",
    "get_enroll_totp",
    "get_magic_link_token_gen",
    "get_password_hasher",
    "get_pre_totp_cache",
    "get_refresh_session",
    "get_regenerate_backup_codes",
    "get_request_magic_link",
    "get_revoke_session",
    "get_token_gen",
    "get_uow_factory",
    "get_verify_totp",
    "install_identity_dependencies",
    "shutdown_identity_dependencies",
]
