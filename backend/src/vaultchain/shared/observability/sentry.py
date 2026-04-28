"""Sentry SDK init for the backend api + worker.

Phase 1 ships the wire-up; the actual DSN comes from the production
``/etc/vaultchain/env`` file via ``SENTRY_DSN_BACKEND``. When the DSN
is unset (dev/CI/test) ``init_sentry`` is a no-op so nothing leaks
externally.

ADR-012 caps backend traces at 5% to stay inside Sentry's free-tier
budget (5K errors/month).
"""

from __future__ import annotations

import os

import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration


def init_sentry(*, dsn: str | None, environment: str) -> bool:
    """Initialize Sentry. Returns True if init actually attached."""
    if not dsn:
        return False

    release = os.environ.get("GIT_SHA") or os.environ.get("GITHUB_SHA")

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        traces_sample_rate=0.05,
        send_default_pii=False,
        integrations=[
            FastApiIntegration(),
            StarletteIntegration(),
            AsyncioIntegration(),
        ],
    )
    return True


__all__ = ["init_sentry"]
