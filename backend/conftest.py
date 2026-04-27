"""Backend pytest root conftest.

Registers hypothesis profiles per spec §7.2. Active profile selected via
HYPOTHESIS_PROFILE env var (default 'dev').
"""
from __future__ import annotations

import os
from datetime import timedelta

from hypothesis import HealthCheck, settings

settings.register_profile("dev", max_examples=10, deadline=None)
settings.register_profile(
    "ci",
    max_examples=50,
    deadline=timedelta(seconds=10),
)
settings.register_profile(
    "nightly",
    max_examples=500,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "dev"))
