"""VerifyTotp use case — AC-phase1-identity-003-04, -05, -06, -07, -08.

Verifies a TOTP code OR a backup code. Success clears the failure
counter and emits ``TotpVerified``. TOTP failure increments the
counter and emits ``TotpVerificationFailed`` (consumed by the
lockout-counter handler that owns the lockout transition itself).
The lockout window is self-healing: when ``locked_until`` is in the
past, verification proceeds and the counter resets.

Backup codes follow the same success path but DO NOT consume the
failure counter on miss (AC-08 — usability/security tradeoff
documented in the brief). A used backup code is removed in the same
UoW (one-time use).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from vaultchain.identity.domain.aggregates import TOTP_LOCKOUT_THRESHOLD
from vaultchain.identity.domain.errors import TotpNotEnrolled, UserLocked
from vaultchain.identity.domain.events import (
    TotpVerificationFailed,
    TotpVerified,
)
from vaultchain.identity.domain.ports import (
    BackupCodeService,
    TotpCodeChecker,
    TotpSecretEncryptor,
    TotpSecretRepository,
    UserRepository,
)
from vaultchain.shared.domain.errors import NotFoundError
from vaultchain.shared.unit_of_work import AbstractUnitOfWork


@dataclass(frozen=True)
class TotpVerifyResult:
    """``attempts_remaining`` is None on success; otherwise 5 - failed_count."""

    success: bool
    attempts_remaining: int | None


class VerifyTotp:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], AbstractUnitOfWork],
        users: Callable[[Any], UserRepository],
        totps: Callable[[Any], TotpSecretRepository],
        encryptor: TotpSecretEncryptor,
        code_checker: TotpCodeChecker,
        backup_codes: BackupCodeService,
    ) -> None:
        self._uow_factory = uow_factory
        self._users = users
        self._totps = totps
        self._encryptor = encryptor
        self._code_checker = code_checker
        self._backup_codes = backup_codes

    async def execute(
        self,
        *,
        user_id: UUID,
        code: str,
        use_backup_code: bool = False,
    ) -> TotpVerifyResult:
        async with self._uow_factory() as uow:
            users = self._users(uow.session)
            totps = self._totps(uow.session)

            user = await users.get_by_id(user_id)
            if user is None:
                raise NotFoundError(details={"user_id": str(user_id)})

            # AC-07: self-healing lockout — window in the past clears state.
            if user.locked_until is not None and not user.is_locked_now():
                user.clear_totp_failures()
                await users.update(user)

            elif user.is_locked_now():
                raise UserLocked(
                    details={
                        "user_id": str(user_id),
                        "locked_until": user.locked_until.isoformat()
                        if user.locked_until
                        else None,
                    }
                )

            secret = await totps.get_by_user_id(user_id)
            if secret is None:
                raise TotpNotEnrolled(details={"user_id": str(user_id)})

            if use_backup_code:
                # AC-08 — backup code: success removes the matching hash;
                # miss does NOT consume the failure counter.
                match = self._backup_codes.find_matching_hash(
                    code, list(secret.backup_codes_hashed)
                )
                if match is None:
                    return TotpVerifyResult(
                        success=False,
                        attempts_remaining=max(
                            TOTP_LOCKOUT_THRESHOLD - user.failed_totp_attempts, 0
                        ),
                    )
                secret.backup_codes_hashed = [h for h in secret.backup_codes_hashed if h != match]
                from datetime import UTC, datetime

                secret.last_verified_at = datetime.now(UTC)
                await totps.update(secret)
                if user.failed_totp_attempts != 0:
                    user.clear_totp_failures()
                    await users.update(user)
                uow.add_event(
                    TotpVerified(
                        aggregate_id=secret.id,
                        user_id=user_id,
                        last_verified_at=secret.last_verified_at,
                    )
                )
                await uow.commit()
                return TotpVerifyResult(success=True, attempts_remaining=None)

            # Standard TOTP path.
            secret_plain = secret.decrypt(self._encryptor)
            ok = self._code_checker.verify(secret_plain, code)

            if ok:
                from datetime import UTC, datetime

                secret.last_verified_at = datetime.now(UTC)
                await totps.update(secret)
                if user.failed_totp_attempts != 0:
                    user.clear_totp_failures()
                    await users.update(user)
                uow.add_event(
                    TotpVerified(
                        aggregate_id=secret.id,
                        user_id=user_id,
                        last_verified_at=secret.last_verified_at,
                    )
                )
                await uow.commit()
                return TotpVerifyResult(success=True, attempts_remaining=None)

            user.record_totp_failure()
            await users.update(user)
            uow.add_event(
                TotpVerificationFailed(
                    aggregate_id=user_id,
                    user_id=user_id,
                    failed_attempts=user.failed_totp_attempts,
                )
            )
            await uow.commit()
            return TotpVerifyResult(
                success=False,
                attempts_remaining=max(TOTP_LOCKOUT_THRESHOLD - user.failed_totp_attempts, 0),
            )


__all__ = ["TotpVerifyResult", "VerifyTotp"]
