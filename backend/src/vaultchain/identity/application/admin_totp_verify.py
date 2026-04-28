"""AdminTotpVerify use case — phase1-admin-002a AC-03, AC-07.

Wraps the existing ``VerifyTotp`` use case from phase1-identity-003 to
preserve a single TOTP failure counter / lockout transition for the
user; on success creates an admin-actor session via ``CreateSession``
and emits the ``audit.AdminAuthenticated`` event so the Phase-2 audit
subscriber can replay the login from the outbox.

The route layer is responsible for cookie composition; this use case
returns the raw tokens once.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from vaultchain.identity.application.create_session import CreateSession, CreateSessionResult
from vaultchain.identity.application.verify_totp import VerifyTotp
from vaultchain.identity.domain.errors import InvalidCredentials
from vaultchain.identity.domain.events import AdminAuthenticated, UserAuthenticated
from vaultchain.identity.domain.ports import UserRepository
from vaultchain.shared.unit_of_work import AbstractUnitOfWork

#: Scope tuple advertised to the access-token cache for admin sessions —
#: the admin auth dependency reads this to differentiate user vs admin.
ADMIN_SCOPES: tuple[str, ...] = ("admin",)


@dataclass(frozen=True)
class AdminTotpVerifyResult:
    user_id: UUID
    email: str
    full_name: str
    role: str
    session: CreateSessionResult


class AdminTotpVerify:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], AbstractUnitOfWork],
        users: Callable[[Any], UserRepository],
        verify_totp: VerifyTotp,
        create_session: CreateSession,
    ) -> None:
        self._uow_factory = uow_factory
        self._users = users
        self._verify_totp = verify_totp
        self._create_session = create_session

    async def execute(
        self,
        *,
        user_id: UUID,
        code: str,
        ip: str | None = None,
        user_agent: str = "",
    ) -> AdminTotpVerifyResult:
        # Reuse the user-side TOTP verify state machine: same lockout
        # counter, same self-healing semantics, same backup-code path.
        result = await self._verify_totp.execute(user_id=user_id, code=code)
        if not result.success:
            # Surface the same envelope a wrong password produced — the
            # route mapping converts to 401 without leaking *which* gate
            # rejected the credentials.
            raise InvalidCredentials(
                details={
                    "reason": "totp_failed",
                    "attempts_remaining": result.attempts_remaining,
                }
            )

        async with self._uow_factory() as uow:
            user = await self._users(uow.session).get_by_id(user_id)
        if user is None or not user.is_admin():
            raise InvalidCredentials(details={"reason": "non_admin_session"})

        session = await self._create_session.execute(
            user_id=user_id,
            user_agent=user_agent,
            ip=ip,
            scopes=ADMIN_SCOPES,
        )

        # Publish the audit event via a fresh UoW so it lands in the outbox
        # in the same DB even though no consumer exists yet (Phase 2 ships it).
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            uow.add_event(
                AdminAuthenticated(
                    aggregate_id=user.id,
                    admin_id=user.id,
                    ip=ip,
                    user_agent=user_agent,
                    login_at=now,
                )
            )
            uow.add_event(
                UserAuthenticated(aggregate_id=user.id, actor_type="admin"),
            )
            await uow.commit()

        return AdminTotpVerifyResult(
            user_id=user.id,
            email=user.email,
            full_name=str(user.metadata.get("full_name", "")),
            role=str(user.metadata.get("admin_role", "admin")),
            session=session,
        )


__all__ = ["ADMIN_SCOPES", "AdminTotpVerify", "AdminTotpVerifyResult"]
