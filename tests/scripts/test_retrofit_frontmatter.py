"""Tests for scripts.retrofit_frontmatter.

Coverage:
- Brief WITHOUT existing frontmatter gets one inserted
- Brief WITH existing frontmatter is left alone (idempotent)
- `## Status` block is removed from body
- Field extraction: complexity from "Complexity:" line; estimated_hours from "Estimated:"; etc.
- ac_count is computed by counting AC-NN: tokens
- depends_on is parsed from "Depends on:" bullets
"""
from __future__ import annotations

import sys
from pathlib import Path

import frontmatter

REPO_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.retrofit_frontmatter import retrofit_brief, parse_status_section  # noqa: E402


def _brief_without_fm(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_status_block_parsed(tmp_path: Path) -> None:
    body = """\
# phase1-identity-002

## Status

- **Phase:** 1
- **Context:** identity
- **Complexity:** L
- **SDD mode:** strict
- **Estimated:** 6h
- **State:** ready
- **Depends on:** phase1-identity-001, phase1-shared-003
- **Blocks:** phase1-identity-005
- **Touches ADRs:** ADR-002, ADR-003

## Title

Magic-link signup/login + console email adapter

## Acceptance Criteria

- AC-01: ...
- AC-02: ...
- AC-03: ...
"""
    fields = parse_status_section(body, brief_id="phase1-identity-002")
    assert fields["phase"] == 1
    assert fields["context"] == "identity"
    assert fields["complexity"] == "L"
    assert fields["sdd_mode"] == "strict"
    assert fields["estimated_hours"] == 6
    assert fields["state"] == "ready"
    assert fields["depends_on"] == ["phase1-identity-001", "phase1-shared-003"]
    assert fields["blocks"] == ["phase1-identity-005"]
    assert fields["touches_adrs"] == ["ADR-002", "ADR-003"]
    assert fields["ac_count"] == 3


def test_retrofit_inserts_frontmatter(tmp_path: Path) -> None:
    target = tmp_path / "phase1-identity-002.md"
    _brief_without_fm(target, """\
# phase1-identity-002

## Status

- **Phase:** 1
- **Context:** identity
- **Complexity:** M
- **SDD mode:** strict
- **Estimated:** 4h
- **State:** ready
- **Depends on:** (none)
- **Blocks:** (none)
- **Touches ADRs:** ADR-002

## Title

Test brief

## Acceptance Criteria

- AC-01: x
- AC-02: y
""")
    retrofit_brief(target)
    doc = frontmatter.load(target)
    assert doc["id"] == "phase1-identity-002"
    assert doc["phase"] == 1
    assert doc["complexity"] == "M"
    assert doc["ac_count"] == 2
    assert "## Status" not in doc.content


def test_retrofit_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "phase1-identity-002.md"
    target.write_text("""\
---
id: phase1-identity-002
phase: 1
context: identity
title: Already has frontmatter
complexity: M
sdd_mode: strict
estimated_hours: 4
state: ready
depends_on: []
blocks: []
touches_adrs: [ADR-002]
ac_count: 2
---

# phase1-identity-002
""", encoding="utf-8")
    before = target.read_text(encoding="utf-8")
    retrofit_brief(target)
    after = target.read_text(encoding="utf-8")
    assert before == after
