"""Tests for scripts.validate_frontmatter.

Coverage:
- Valid brief passes
- Missing required field fails
- id mismatch with filename fails
- Unknown context value fails
- depends_on points to non-existent brief fails
- Cyclic depends_on fails
- ac_count < 1 fails
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.validate_frontmatter import validate_repo  # noqa: E402
from tests.scripts.conftest import write_brief  # noqa: E402


def _good_fm(brief_id: str = "phase1-identity-001") -> dict:
    return {
        "id": brief_id,
        "phase": int(brief_id[5]),
        "context": "identity",
        "title": "Test brief",
        "complexity": "M",
        "sdd_mode": "strict",
        "estimated_hours": 4,
        "state": "ready",
        "depends_on": [],
        "blocks": [],
        "touches_adrs": ["ADR-001"],
        "ac_count": 5,
    }


def test_valid_brief_passes(tmp_repo: Path) -> None:
    write_brief(tmp_repo, "phase1-identity-001", _good_fm())
    errors = validate_repo(tmp_repo)
    assert errors == []


def test_missing_required_field_fails(tmp_repo: Path) -> None:
    fm = _good_fm()
    del fm["title"]
    write_brief(tmp_repo, "phase1-identity-001", fm)
    errors = validate_repo(tmp_repo)
    assert any("title" in e for e in errors)


def test_id_mismatch_with_filename_fails(tmp_repo: Path) -> None:
    fm = _good_fm("phase1-identity-001")
    fm["id"] = "phase1-identity-999"  # mismatch
    write_brief(tmp_repo, "phase1-identity-001", fm)
    errors = validate_repo(tmp_repo)
    assert any("id mismatch" in e.lower() for e in errors)


def test_unknown_context_fails(tmp_repo: Path) -> None:
    fm = _good_fm()
    fm["context"] = "spaceship"
    write_brief(tmp_repo, "phase1-identity-001", fm)
    errors = validate_repo(tmp_repo)
    assert any("context" in e.lower() for e in errors)


def test_dangling_dependency_fails(tmp_repo: Path) -> None:
    fm = _good_fm()
    fm["depends_on"] = ["phase1-identity-999"]
    write_brief(tmp_repo, "phase1-identity-001", fm)
    errors = validate_repo(tmp_repo)
    assert any("phase1-identity-999" in e for e in errors)


def test_cycle_in_dependencies_fails(tmp_repo: Path) -> None:
    fm_a = _good_fm("phase1-identity-001")
    fm_a["depends_on"] = ["phase1-identity-002"]
    fm_b = _good_fm("phase1-identity-002")
    fm_b["depends_on"] = ["phase1-identity-001"]
    write_brief(tmp_repo, "phase1-identity-001", fm_a)
    write_brief(tmp_repo, "phase1-identity-002", fm_b)
    errors = validate_repo(tmp_repo)
    assert any("cycle" in e.lower() for e in errors)


def test_ac_count_zero_fails(tmp_repo: Path) -> None:
    fm = _good_fm()
    fm["ac_count"] = 0
    write_brief(tmp_repo, "phase1-identity-001", fm)
    errors = validate_repo(tmp_repo)
    assert any("ac_count" in e.lower() for e in errors)
