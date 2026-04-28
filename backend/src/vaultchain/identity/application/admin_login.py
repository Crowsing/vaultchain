"""AdminLogin use case — phase1-admin-002a AC-01, AC-02.

Validates an admin's email + password, increments the password-failure
counter on miss, applies the 5-failure / 30-min lockout when the
threshold trips, and on success returns a fresh pre-TOTP token. The
TOTP verify step (``AdminTotpVerify``) consumes the token and mints
the actual session.

Security shape:
- Same ``InvalidCredentials`` code for "email unknown" and "wrong
  password" — never leak which leg failed.
- bcrypt verify even on unknown email is intentional (timing parity)
  but expensive; we therefore short-circuit on the unknown-email path
  *only after* we've performed an equivalent-cost dummy verify against
  a fixed hash. That keeps the email-unknown vs. wrong-password latency
  indistinguishable to the caller.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from vaultchain.identity.domain.errors import (
    InvalidCredentials,
    UserLocked,
)
from vaultchain.identity.domain.ports import PasswordHasher, UserRepository
from vaultchain.identity.domain.value_objects import Email
from vaultchain.shared.unit_of_work import AbstractUnitOfWork

#: Fixed bcrypt hash used to keep the unknown-email branch's latency on
#: par with a real verify. Generated once at import time; the value is
#: irrelevant — only the cost matters.
_DUMMY_HASH = "$2b$12$" + "C" * 53  # invalid but well-shaped placeholder


@dataclass(frozen=True)
class AdminLoginResult:
    """``user_id`` is what the route stuffs into the pre-TOTP cache."""

    user_id: UUID


class AdminLogin:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], AbstractUnitOfWork],
        users: Callable[[Any], UserRepository],
        password_hasher: PasswordHasher,
    ) -> None:
        self._uow_factory = uow_factory
        self._users = users
        self._password_hasher = password_hasher

    async def execute(self, *, email: str, password: str) -> AdminLoginResult:
        normalized = Email(email).value

        async with self._uow_factory() as uow:
            users = self._users(uow.session)
            user = await users.get_by_email(normalized)

            if user is None or not user.is_admin() or user.password_hash is None:
                # Timing-parity dummy verify so the unknown-email branch
                # cannot be distinguished from a wrong-password branch.
                self._password_hasher.verify(password, _DUMMY_HASH)
                raise InvalidCredentials(details={"reason": "unknown_or_non_admin"})

            # Self-healing lockout: if the window elapsed, clear state and proceed.
            now = datetime.now(UTC)
            if user.locked_until is not None and not user.is_locked_now(now=now):
                user.clear_password_lockout(now=now)
                await users.update(user)
            elif user.is_locked_now(now=now):
                raise UserLocked(
                    details={
                        "user_id": str(user.id),
                        "locked_until": user.locked_until.isoformat()
                        if user.locked_until
                        else None,
                    }
                )

            pre_version = user.version
            pre_failures = user.login_failure_count

            ok = self._password_hasher.verify(password, user.password_hash)
            if not ok:
                threshold_reached = user.record_password_failure(now=now)
                if threshold_reached:
                    user.lock_due_to_password_failures(now=now)
                await users.update(user)
                await uow.commit()
                raise InvalidCredentials(details={"reason": "wrong_password"})

            # Success path: only persist when the failure counter was non-zero.
            if pre_failures != 0:
                user.clear_password_failures(now=now)
            if user.version != pre_version:
                await users.update(user)
            await uow.commit()
            return AdminLoginResult(user_id=user.id)


__all__ = ["AdminLogin", "AdminLoginResult"]
