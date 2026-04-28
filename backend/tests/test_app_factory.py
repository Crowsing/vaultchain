"""Tests for vaultchain.main app factory.

Phase 1 briefs (shared-002 onward) replace this stub with concrete routers.
For bootstrap we only require:
- create_app() returns a FastAPI instance
- /healthz returns 200 with JSON {"status": "ok"}
- App reads config from env (no hard-coded secrets in factory)
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from vaultchain.main import create_app


def test_create_app_returns_fastapi_instance() -> None:
    app = create_app()
    assert isinstance(app, FastAPI)


def test_healthz_reports_db_and_redis_check_keys() -> None:
    """phase1-deploy-001: /healthz pings DB + Redis and reports per-dep status.

    In CI / local-test conditions the DB/Redis pings may genuinely fail
    (no live services pointed at; the test only asserts the *shape* of
    the response, not that every dep is up). Production probes hit the
    real services and so will return 200 with both checks green.
    """
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/healthz")
        # Either 200 (ok) or 503 (one or both deps unreachable in test env).
        assert response.status_code in (200, 503)
        body = response.json()
        assert "status" in body
        assert body["status"] in ("ok", "degraded")
        assert "checks" in body
        assert "database" in body["checks"]
        assert "redis" in body["checks"]


def test_app_factory_idempotent() -> None:
    """Calling create_app() twice should not crash (test isolation)."""
    a = create_app()
    b = create_app()
    assert a is not b
    assert isinstance(a, FastAPI)
    assert isinstance(b, FastAPI)


def test_openapi_declares_idempotency_key_parameter() -> None:
    """phase1-shared-006: a reusable `IdempotencyKey` parameter component is registered."""
    app = create_app()
    schema = app.openapi()
    params = schema.get("components", {}).get("parameters", {})
    assert "IdempotencyKey" in params
    idem = params["IdempotencyKey"]
    assert idem["name"] == "Idempotency-Key"
    assert idem["in"] == "header"
    assert idem["schema"]["maxLength"] == 200
