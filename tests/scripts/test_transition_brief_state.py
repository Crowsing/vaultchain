"""Tests for scripts.transition_brief_state.

Coverage:
- Valid transition (ready → in_progress) updates frontmatter state
- Invalid current state fails (e.g., merged → ready)
- Non-existent brief id fails
- File contents preserved (only state field changes)
"""
from __future__ import annotations

import sys
from pathlib import Path

import frontmatter
import pytest

REPO_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.transition_brief_state import transition  # noqa: E402
from tests.scripts.conftest import write_brief  # noqa: E402


def _fm(brief_id: str, state: str = "ready") -> dict:
    return {
        "id": brief_id,
        "phase": int(brief_id[5]),
        "context": "identity",
        "title": "T",
        "complexity": "M",
        "sdd_mode": "strict",
        "state": state,
        "depends_on": [],
        "blocks": [],
        "touches_adrs": [],
        "ac_count": 1,
    }


def test_ready_to_in_progress(tmp_repo: Path) -> None:
    write_brief(tmp_repo, "phase1-identity-001", _fm("phase1-identity-001", "ready"),
                body="Original body unchanged.")
    transition(tmp_repo, "phase1-identity-001", "in_progress")
    fm = frontmatter.load(tmp_repo / "phase1-briefs" / "phase1-identity-001.md")
    assert fm["state"] == "in_progress"
    assert "Original body unchanged." in fm.content


def test_invalid_transition_fails(tmp_repo: Path) -> None:
    write_brief(tmp_repo, "phase1-identity-001", _fm("phase1-identity-001", "merged"))
    with pytest.raises(ValueError, match="invalid transition"):
        transition(tmp_repo, "phase1-identity-001", "ready")


def test_unknown_brief_fails(tmp_repo: Path) -> None:
    with pytest.raises(FileNotFoundError):
        transition(tmp_repo, "phase1-identity-999", "in_progress")


def test_review_to_merged(tmp_repo: Path) -> None:
    write_brief(tmp_repo, "phase1-identity-001", _fm("phase1-identity-001", "review"))
    transition(tmp_repo, "phase1-identity-001", "merged")
    fm = frontmatter.load(tmp_repo / "phase1-briefs" / "phase1-identity-001.md")
    assert fm["state"] == "merged"


def test_any_to_blocked(tmp_repo: Path) -> None:
    write_brief(tmp_repo, "phase1-identity-001", _fm("phase1-identity-001", "in_progress"))
    transition(tmp_repo, "phase1-identity-001", "blocked")
    fm = frontmatter.load(tmp_repo / "phase1-briefs" / "phase1-identity-001.md")
    assert fm["state"] == "blocked"


def test_blocked_to_ready(tmp_repo: Path) -> None:
    write_brief(tmp_repo, "phase1-identity-001", _fm("phase1-identity-001", "blocked"))
    transition(tmp_repo, "phase1-identity-001", "ready")
    fm = frontmatter.load(tmp_repo / "phase1-briefs" / "phase1-identity-001.md")
    assert fm["state"] == "ready"
