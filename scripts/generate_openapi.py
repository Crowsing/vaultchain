"""Build `docs/api-contract.yaml` from FastAPI's generated OpenAPI schema.

Drives the Stage 8 drift check (CI fails if the committed file diverges
from a fresh rebuild). Run without flags to refresh the artefact;
`--check` exits non-zero when there's a diff.

Phase 1 brief phase1-identity-005 wires the auth router into the app,
so this script now produces the real schema. Future briefs that add
endpoints rely on this same script being idempotent.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import yaml


def _build_app_for_schema() -> Any:
    """Build a FastAPI app with stub env values so `create_app()` boots
    even when the generation runs outside docker / dev.

    The script never actually serves traffic; it only renders the static
    OpenAPI dict. We set placeholder env vars so pydantic-settings stops
    complaining about missing required fields.
    """
    os.environ.setdefault("SECRET_KEY", "x" * 64)
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
    os.environ.setdefault("ENVIRONMENT", "test")

    # Reset the settings cache so the env vars take effect.
    from vaultchain.config import reset_settings_cache

    reset_settings_cache()

    from vaultchain.main import create_app

    return create_app()


def render_schema() -> dict[str, Any]:
    app = _build_app_for_schema()
    return app.openapi()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    contract = repo / "docs" / "api-contract.yaml"
    schema = render_schema()
    rendered = yaml.safe_dump(schema, sort_keys=True, allow_unicode=True)

    if args.check:
        if not contract.exists():
            print(f"{contract} missing — run scripts/generate_openapi.py", file=sys.stderr)
            return 1
        on_disk = contract.read_text(encoding="utf-8")
        if on_disk != rendered:
            print(
                f"OpenAPI drift: {contract} is out of sync; "
                f"rerun `python scripts/generate_openapi.py`.",
                file=sys.stderr,
            )
            return 1
        print("OpenAPI in sync.")
        return 0

    contract.parent.mkdir(parents=True, exist_ok=True)
    contract.write_text(rendered, encoding="utf-8")
    print(f"OpenAPI written to {contract}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
