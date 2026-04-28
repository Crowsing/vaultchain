"""RegenerateBackupCodes use case — AC-phase1-identity-003-09.

Replaces all stored backup-code hashes with a fresh set of 10 codes
in the same UoW. Old codes become invalid atomically; plaintext is
returned exactly once. The route layer (identity-005) is responsible
for gating this with a fresh TOTP verification.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from vaultchain.identity.domain.errors import TotpNotEnrolled
from vaultchain.identity.domain.ports import (
    BackupCodeService,
    TotpSecretRepository,
    UserRepository,
)
from vaultchain.shared.domain.errors import NotFoundError
from vaultchain.shared.unit_of_work import AbstractUnitOfWork


@dataclass(frozen=True)
class BackupCodesRegenerationResult:
    """Plaintext returned ONCE; subsequent reads of the secret never return it."""

    backup_codes_plaintext: list[str]


class RegenerateBackupCodes:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], AbstractUnitOfWork],
        users: Callable[[Any], UserRepository],
        totps: Callable[[Any], TotpSecretRepository],
        backup_codes: BackupCodeService,
    ) -> None:
        self._uow_factory = uow_factory
        self._users = users
        self._totps = totps
        self._backup_codes = backup_codes

    async def execute(self, *, user_id: UUID) -> BackupCodesRegenerationResult:
        async with self._uow_factory() as uow:
            users = self._users(uow.session)
            totps = self._totps(uow.session)

            user = await users.get_by_id(user_id)
            if user is None:
                raise NotFoundError(details={"user_id": str(user_id)})

            secret = await totps.get_by_user_id(user_id)
            if secret is None:
                raise TotpNotEnrolled(details={"user_id": str(user_id)})

            plaintext = self._backup_codes.generate(10)
            secret.backup_codes_hashed = [self._backup_codes.hash(c) for c in plaintext]
            await totps.update(secret)
            await uow.commit()

            return BackupCodesRegenerationResult(backup_codes_plaintext=plaintext)


__all__ = ["BackupCodesRegenerationResult", "RegenerateBackupCodes"]
