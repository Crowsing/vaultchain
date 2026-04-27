"""Architecture test: invokes import-linter as a pytest case.

Failure prints which contract failed. Phase-1 briefs add concrete deps;
this test ensures the contracts themselves remain green from day one.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_import_linter_contracts_pass() -> None:
    """Run `lint-imports` from backend root; non-zero exit fails the test."""
    result = subprocess.run(
        ["lint-imports", "--config", str(BACKEND_ROOT / "pyproject.toml")],
        capture_output=True,
        text=True,
        cwd=BACKEND_ROOT,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            f"import-linter contract violations:\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )
