"""Tests for scripts.phase_summary.

Coverage:
- Empty phase yields a header + zero counts
- All-merged phase yields a summary with counts and brief table
- Mixed-state phase still produces output without crashing (writes counts of unmerged)
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.phase_summary import build_summary  # noqa: E402
from tests.scripts.conftest import write_brief  # noqa: E402


def _fm(brief_id: str, **overrides) -> dict:
    base = {
        "id": brief_id,
        "phase": int(brief_id[5]),
        "context": "identity",
        "title": f"Title {brief_id}",
        "complexity": "M",
        "sdd_mode": "strict",
        "estimated_hours": 4,
        "state": "merged",
        "depends_on": [],
        "blocks": [],
        "touches_adrs": [],
        "ac_count": 5,
    }
    base.update(overrides)
    return base


def test_empty_phase_yields_header(tmp_repo) -> None:
    text = build_summary(tmp_repo, phase=1)
    assert "Phase 1" in text
    assert "0/0" in text or "0 of 0" in text


def test_all_merged_summary(tmp_repo) -> None:
    write_brief(tmp_repo, "phase1-identity-001", _fm("phase1-identity-001"))
    write_brief(tmp_repo, "phase1-identity-002", _fm("phase1-identity-002"))
    text = build_summary(tmp_repo, phase=1)
    assert "phase1-identity-001" in text
    assert "phase1-identity-002" in text
    assert "2 of 2" in text or "2/2" in text


def test_mixed_state_summary(tmp_repo) -> None:
    write_brief(tmp_repo, "phase1-identity-001", _fm("phase1-identity-001", state="merged"))
    write_brief(tmp_repo, "phase1-identity-002", _fm("phase1-identity-002", state="ready"))
    text = build_summary(tmp_repo, phase=1)
    assert "1 of 2" in text or "1/2" in text
