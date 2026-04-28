"""``seed_admin`` operator CLI — phase1-admin-002a AC-06.

Inserts an admin row into ``identity.users`` plus a paired TOTP secret
in ``identity.totp_secrets`` inside a single Unit of Work, then prints
the otpauth URI + 10 backup codes to stdout. Backup codes are shown
exactly once and never logged.

Usage::

    python -m vaultchain.cli.scripts.seed_admin \
        --email admin@vaultchain.io \
        --password "<strong-password>" \
        [--full-name "Demo Admin"] \
        [--role admin] \
        [--accept-secret-display]

A confirmation prompt asks the operator to verify the terminal is
private; ``--accept-secret-display`` skips the prompt for scripted use
(documented as risk in the brief). The CLI fails loud if the email is
already registered — overwrite is never silent.
"""

from __future__ import annotations

import asyncio
from typing import Any

import click

from vaultchain.config import get_settings
from vaultchain.identity.domain.aggregates import TotpSecret, User
from vaultchain.identity.domain.value_objects import (
    ActorType,
    Email,
    PasswordPolicy,
)
from vaultchain.identity.infra.bcrypt_password_hasher import BcryptPasswordHasher
from vaultchain.identity.infra.repositories import (
    SqlAlchemyTotpSecretRepository,
    SqlAlchemyUserRepository,
)
from vaultchain.identity.infra.totp.backup_codes import Argon2BackupCodeService
from vaultchain.identity.infra.totp.pyotp_checker import PyOtpCodeChecker
from vaultchain.identity.infra.totp_encryptor import StaticKeyTotpEncryptor


@click.command()
@click.option("--email", required=True, help="Admin email address.")
@click.option(
    "--password",
    required=True,
    help="Plaintext admin password (≥12 chars).",
)
@click.option("--full-name", default="", help="Admin full name (stored in metadata).")
@click.option("--role", default="admin", help="Admin role label (default: admin).")
@click.option(
    "--accept-secret-display",
    is_flag=True,
    default=False,
    help="Skip the private-terminal confirmation prompt.",
)
def main(
    email: str,
    password: str,
    full_name: str,
    role: str,
    accept_secret_display: bool,
) -> None:
    """Provision an admin row + paired TOTP secret, print backup codes once."""
    asyncio.run(
        _seed(
            email=email,
            password=password,
            full_name=full_name,
            role=role,
            accept_secret_display=accept_secret_display,
        )
    )


async def _seed(
    *,
    email: str,
    password: str,
    full_name: str,
    role: str,
    accept_secret_display: bool,
) -> None:
    if not accept_secret_display and not click.confirm(
        "Backup codes will be displayed once. Are you in a private terminal?",
        default=False,
    ):
        click.echo("Aborted: re-run in a private terminal or pass --accept-secret-display.")
        raise SystemExit(2)

    # Validate inputs at the domain layer so we never insert a malformed row.
    normalized_email = Email(email).value
    PasswordPolicy().validate(password)

    settings = get_settings()
    hasher = BcryptPasswordHasher()
    encryptor = StaticKeyTotpEncryptor(
        key=settings.secret_key.get_secret_value().encode("utf-8")[:32].ljust(32, b"\x00")
    )
    totp_checker = PyOtpCodeChecker()
    backup_codes = Argon2BackupCodeService()

    password_hash = hasher.hash(password)
    secret_plain = totp_checker.generate_secret()
    plain_codes = backup_codes.generate(count=10)
    hashed_codes = [backup_codes.hash(c) for c in plain_codes]

    user = User.seed_admin(
        email=normalized_email,
        email_hash=Email(normalized_email).hash_blake2b(),
        password_hash=password_hash,
        full_name=full_name,
        role=role,
    )
    secret = TotpSecret.enroll(
        user_id=user.id,
        secret_plain=secret_plain,
        backup_codes_hashed=hashed_codes,
        encryptor=encryptor,
    )

    qr_uri = totp_checker.qr_payload_uri(email=normalized_email, secret=secret_plain)

    await _persist(user=user, secret=secret, database_url=settings.database_url)

    click.echo(f"Admin seeded: {normalized_email}")
    click.echo(f"otpauth URI: {qr_uri}")
    click.echo("Backup codes (write these down — shown once):")
    for code in plain_codes:
        click.echo(f"  {code}")


async def _persist(*, user: User, secret: TotpSecret, database_url: str) -> None:
    """Insert both rows in a single transaction; fail loud on duplicate."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(database_url, future=True)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session, session.begin():
            users = SqlAlchemyUserRepository(session)
            existing = await users.get_by_email(user.email)
            if existing is not None:
                raise click.ClickException(
                    f"User with email {user.email!r} already exists; refusing to overwrite."
                )
            await users.add(user)
            await SqlAlchemyTotpSecretRepository(session).add(secret)
    finally:
        await engine.dispose()


def run_via_runner(runner: Any, **kwargs: Any) -> Any:
    """Test helper: invoke the click command via a CliRunner."""
    return runner.invoke(main, **kwargs)


# Touching `ActorType` so import-organizers don't drop it; the seed path
# uses it transitively via ``User.seed_admin`` and tests assert on it.
_ = ActorType


if __name__ == "__main__":  # pragma: no cover
    main()
