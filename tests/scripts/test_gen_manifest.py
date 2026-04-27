"""Tests for scripts.gen_manifest.

Coverage:
- Empty briefs → manifest with empty briefs list, phase-pointer copied
- Single brief → manifest contains it
- Sorting: by (phase, id) ascending
- Aggregations: by_phase, by_state, by_context counts
- dependency-graph.mmd: produces valid mermaid syntax
- --check mode: returns 0 if no drift, 1 if drift
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.gen_manifest import generate_manifest, generate_mermaid, run_check  # noqa: E402
from tests.scripts.conftest import write_brief  # noqa: E402


def _good_fm(brief_id: str, **overrides) -> dict:
    base = {
        "id": brief_id,
        "phase": int(brief_id[5]),
        "context": "identity",
        "title": f"Brief {brief_id}",
        "complexity": "M",
        "sdd_mode": "strict",
        "estimated_hours": 4,
        "state": "ready",
        "depends_on": [],
        "blocks": [],
        "touches_adrs": [],
        "ac_count": 3,
    }
    base.update(overrides)
    return base


def test_empty_repo_yields_empty_manifest(tmp_repo: Path) -> None:
    manifest = generate_manifest(tmp_repo)
    assert manifest["briefs"] == []
    assert manifest["current_phase"] == 1
    assert manifest["phase_state"] == "in_progress"
    assert manifest["counts"]["total"] == 0


def test_single_brief_appears_in_manifest(tmp_repo: Path) -> None:
    write_brief(tmp_repo, "phase1-identity-001", _good_fm("phase1-identity-001"))
    manifest = generate_manifest(tmp_repo)
    assert len(manifest["briefs"]) == 1
    assert manifest["briefs"][0]["id"] == "phase1-identity-001"
    assert manifest["counts"]["total"] == 1
    assert manifest["counts"]["by_state"]["ready"] == 1
    assert manifest["counts"]["by_phase"][1] == 1
    assert manifest["counts"]["by_context"]["identity"] == 1


def test_briefs_sorted_by_phase_then_id(tmp_repo: Path) -> None:
    write_brief(tmp_repo, "phase2-wallet-001", _good_fm("phase2-wallet-001", context="wallet"))
    write_brief(tmp_repo, "phase1-identity-002", _good_fm("phase1-identity-002"))
    write_brief(tmp_repo, "phase1-identity-001", _good_fm("phase1-identity-001"))
    manifest = generate_manifest(tmp_repo)
    ids = [b["id"] for b in manifest["briefs"]]
    assert ids == ["phase1-identity-001", "phase1-identity-002", "phase2-wallet-001"]


def test_counts_by_state(tmp_repo: Path) -> None:
    write_brief(tmp_repo, "phase1-identity-001", _good_fm("phase1-identity-001", state="merged"))
    write_brief(tmp_repo, "phase1-identity-002", _good_fm("phase1-identity-002", state="ready"))
    write_brief(tmp_repo, "phase1-identity-003", _good_fm("phase1-identity-003", state="blocked"))
    manifest = generate_manifest(tmp_repo)
    assert manifest["counts"]["by_state"] == {"merged": 1, "ready": 1, "blocked": 1}


def test_mermaid_lists_dependency_edges(tmp_repo: Path) -> None:
    write_brief(tmp_repo, "phase1-identity-001", _good_fm("phase1-identity-001"))
    write_brief(
        tmp_repo, "phase1-identity-002",
        _good_fm("phase1-identity-002", depends_on=["phase1-identity-001"]),
    )
    mmd = generate_mermaid(tmp_repo)
    assert "graph LR" in mmd or "flowchart" in mmd
    assert "phase1-identity-001" in mmd
    assert "phase1-identity-002" in mmd
    assert "-->" in mmd


def test_check_mode_passes_when_committed_matches(tmp_repo: Path) -> None:
    write_brief(tmp_repo, "phase1-identity-001", _good_fm("phase1-identity-001"))
    manifest = generate_manifest(tmp_repo)
    (tmp_repo / "docs" / "briefs" / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8",
    )
    rc = run_check(tmp_repo)
    assert rc == 0


def test_check_mode_fails_when_committed_drifts(tmp_repo: Path) -> None:
    write_brief(tmp_repo, "phase1-identity-001", _good_fm("phase1-identity-001"))
    (tmp_repo / "docs" / "briefs" / "manifest.yaml").write_text(
        "briefs: []\ncurrent_phase: 1\nphase_state: in_progress\n", encoding="utf-8",
    )
    rc = run_check(tmp_repo)
    assert rc == 1
