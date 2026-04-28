"""EnrollTotp use case — AC-phase1-identity-003-02, -03, -10.

Generates a fresh TOTP secret + 10 backup codes, persists encrypted
secret + argon2id-hashed codes, captures ``TotpEnrolled`` event, and
returns plaintext exactly once. Re-enrollment is blocked at the
domain level via ``TotpAlreadyEnrolled``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from vaultchain.identity.domain.aggregates import TotpSecret
from vaultchain.identity.domain.errors import TotpAlreadyEnrolled
from vaultchain.identity.domain.events import TotpEnrolled
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
class TotpEnrollmentResult:
    """Plaintext returned ONCE; re-fetching the secret never returns plaintext."""

    secret_for_qr: str
    qr_payload_uri: str
    backup_codes_plaintext: list[str]


class EnrollTotp:
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

    async def execute(self, *, user_id: UUID) -> TotpEnrollmentResult:
        async with self._uow_factory() as uow:
            users = self._users(uow.session)
            totps = self._totps(uow.session)

            user = await users.get_by_id(user_id)
            if user is None:
                raise NotFoundError(details={"user_id": str(user_id)})

            existing = await totps.get_by_user_id(user_id)
            if existing is not None:
                raise TotpAlreadyEnrolled(details={"user_id": str(user_id)})

            secret_plain = self._code_checker.generate_secret()
            backup_plaintext = self._backup_codes.generate(10)
            backup_hashes = [self._backup_codes.hash(c) for c in backup_plaintext]

            secret = TotpSecret.enroll(
                user_id=user_id,
                secret_plain=secret_plain,
                backup_codes_hashed=backup_hashes,
                encryptor=self._encryptor,
            )
            await totps.add(secret)
            uow.add_event(TotpEnrolled(aggregate_id=secret.id, user_id=user_id))
            await uow.commit()

            return TotpEnrollmentResult(
                secret_for_qr=secret_plain.decode("ascii"),
                qr_payload_uri=self._code_checker.qr_payload_uri(
                    email=user.email, secret=secret_plain
                ),
                backup_codes_plaintext=backup_plaintext,
            )


__all__ = ["EnrollTotp", "TotpEnrollmentResult"]
