"""Tests for scripts.check_coverage.

Coverage:
- All thresholds met → exit 0
- One directory below threshold → exit 1 with descriptive message
- Missing coverage data → exit 2 with explanatory message
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.check_coverage import check_thresholds  # noqa: E402


def _make_coverage_xml(path: Path, packages: dict[str, float]) -> None:
    """Build a minimal coverage.xml that the script can parse."""
    lines = ['<?xml version="1.0"?>', '<coverage>', '  <packages>']
    for pkg, rate in packages.items():
        lines.append(f'    <package name="{pkg}" line-rate="{rate}">')
        lines.append('    </package>')
    lines.append('  </packages>')
    lines.append('</coverage>')
    path.write_text("\n".join(lines), encoding="utf-8")


def test_all_thresholds_met(tmp_path: Path) -> None:
    cov = tmp_path / "coverage.xml"
    _make_coverage_xml(cov, {
        "vaultchain.shared.domain": 0.96,
        "vaultchain.identity.domain": 0.92,
        "vaultchain.identity.application": 0.86,
    })
    rc, errors = check_thresholds(cov)
    assert rc == 0
    assert errors == []


def test_below_threshold_fails(tmp_path: Path) -> None:
    cov = tmp_path / "coverage.xml"
    _make_coverage_xml(cov, {
        "vaultchain.shared.domain": 0.80,  # needs 0.95
    })
    rc, errors = check_thresholds(cov)
    assert rc == 1
    assert any("vaultchain.shared.domain" in e for e in errors)
    assert any("0.80" in e or "80" in e for e in errors)


def test_missing_coverage_xml(tmp_path: Path) -> None:
    rc, errors = check_thresholds(tmp_path / "nonexistent.xml")
    assert rc == 2
    assert any("not found" in e.lower() for e in errors)
