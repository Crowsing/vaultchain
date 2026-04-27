"""Shared fixtures for script tests.

The `tmp_repo` fixture creates a minimal fake repo layout
inside a tmp_path so tests don't touch real briefs.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Build a minimal repo skeleton under tmp_path.

    Layout:
        tmp_path/
            phase1-briefs/
                _frontmatter-schema.yaml  (copied from real)
            phase2-briefs/
            phase3-briefs/
            phase4-briefs/
            docs/briefs/
                phase_pointer.yaml
            docs/progress/
    """
    real_schema = Path(__file__).parents[2] / "phase1-briefs" / "_frontmatter-schema.yaml"
    for p in ("phase1-briefs", "phase2-briefs", "phase3-briefs", "phase4-briefs"):
        (tmp_path / p).mkdir(parents=True)
    (tmp_path / "docs" / "briefs").mkdir(parents=True)
    (tmp_path / "docs" / "progress").mkdir(parents=True)
    (tmp_path / "phase1-briefs" / "_frontmatter-schema.yaml").write_text(
        real_schema.read_text(encoding="utf-8"), encoding="utf-8",
    )
    (tmp_path / "docs" / "briefs" / "phase_pointer.yaml").write_text(
        "current_phase: 1\nphase_state: in_progress\n", encoding="utf-8",
    )
    return tmp_path


def write_brief(repo: Path, brief_id: str, frontmatter: dict, body: str = "Body.") -> Path:
    """Helper used across script tests."""
    import yaml
    phase = brief_id.split("-")[0]
    target = repo / f"{phase}-briefs" / f"{brief_id}.md"
    fm_text = yaml.safe_dump(frontmatter, sort_keys=False)
    target.write_text(f"---\n{fm_text}---\n\n# {brief_id}\n\n{body}\n", encoding="utf-8")
    return target
