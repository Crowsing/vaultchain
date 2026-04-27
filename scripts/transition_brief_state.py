"""CLI: edit a brief's frontmatter `state` field with state-machine validation.

State machine (per spec §4.3):
    ready          → in_progress | blocked | obsolete
    in_progress    → review | blocked | obsolete
    review         → merged | blocked | in_progress | obsolete
    merged         → obsolete
    blocked        → ready | obsolete
    obsolete       → (terminal)

Usage:
    python scripts/transition_brief_state.py phase1-identity-002 in_progress
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import frontmatter

VALID_TRANSITIONS: dict[str, set[str]] = {
    "ready": {"in_progress", "blocked", "obsolete"},
    "in_progress": {"review", "blocked", "obsolete"},
    "review": {"merged", "blocked", "in_progress", "obsolete"},
    "merged": {"obsolete"},
    "blocked": {"ready", "obsolete"},
    "obsolete": set(),
}


def _find_brief(repo_root: Path, brief_id: str) -> Path:
    if not brief_id.startswith("phase") or len(brief_id) < 7:
        raise ValueError(f"invalid brief id format: {brief_id}")
    phase = brief_id[:6]
    candidate = repo_root / f"{phase}-briefs" / f"{brief_id}.md"
    if not candidate.exists():
        raise FileNotFoundError(f"no such brief: {candidate}")
    return candidate


def transition(repo_root: Path, brief_id: str, target_state: str) -> None:
    """Apply a state transition. Raises on invalid input."""
    path = _find_brief(repo_root, brief_id)
    doc = frontmatter.load(path)
    current = doc.get("state")
    if current not in VALID_TRANSITIONS:
        raise ValueError(f"unknown current state on {brief_id}: {current!r}")
    allowed = VALID_TRANSITIONS[current]
    if target_state not in allowed:
        raise ValueError(
            f"invalid transition for {brief_id}: {current} -> {target_state} "
            f"(allowed: {sorted(allowed)})"
        )
    doc["state"] = target_state
    path.write_text(frontmatter.dumps(doc) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("brief_id")
    parser.add_argument("target_state",
                        choices=["ready", "in_progress", "review", "merged", "blocked", "obsolete"])
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    try:
        transition(repo, args.brief_id, args.target_state)
    except (ValueError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"{args.brief_id}: state -> {args.target_state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
