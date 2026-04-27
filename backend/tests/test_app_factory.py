"""Tests for vaultchain.main app factory.

Phase 1 briefs (shared-002 onward) replace this stub with concrete routers.
For bootstrap we only require:
- create_app() returns a FastAPI instance
- /healthz returns 200 with JSON {"status": "ok"}
- App reads config from env (no hard-coded secrets in factory)
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vaultchain.main import create_app


def test_create_app_returns_fastapi_instance() -> None:
    app = create_app()
    assert isinstance(app, FastAPI)


def test_healthz_returns_ok() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_app_factory_idempotent() -> None:
    """Calling create_app() twice should not crash (test isolation)."""
    a = create_app()
    b = create_app()
    assert a is not b
    assert isinstance(a, FastAPI)
    assert isinstance(b, FastAPI)
