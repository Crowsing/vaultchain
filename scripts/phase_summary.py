"""Build docs/progress/phase{N}-summary.md from brief frontmatter.

Triggered by /autonomous-build at phase exit.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import frontmatter


def _iter_phase_briefs(repo_root: Path, phase: int) -> Iterator[Path]:
    d = repo_root / f"phase{phase}-briefs"
    if not d.is_dir():
        return
    for f in sorted(d.glob("*.md")):
        if f.name.startswith("_"):
            continue
        yield f


def build_summary(repo_root: Path, phase: int) -> str:
    briefs = []
    for path in _iter_phase_briefs(repo_root, phase):
        meta = dict(frontmatter.load(path).metadata)
        if not meta:
            continue
        briefs.append(meta)
    total = len(briefs)
    merged = sum(1 for b in briefs if b.get("state") == "merged")
    by_state: dict[str, int] = {}
    by_context: dict[str, int] = {}
    for b in briefs:
        by_state[b["state"]] = by_state.get(b["state"], 0) + 1
        by_context[b["context"]] = by_context.get(b["context"], 0) + 1

    lines = []
    lines.append(f"# Phase {phase} Summary")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    lines.append(f"**Briefs merged:** {merged} of {total} ({merged}/{total})")
    lines.append("")
    lines.append("## State distribution")
    lines.append("")
    for s, c in sorted(by_state.items()):
        lines.append(f"- `{s}`: {c}")
    lines.append("")
    lines.append("## By context")
    lines.append("")
    for c, n in sorted(by_context.items()):
        lines.append(f"- `{c}`: {n}")
    lines.append("")
    lines.append("## Brief inventory")
    lines.append("")
    lines.append("| ID | State | Complexity | Title |")
    lines.append("|----|-------|------------|-------|")
    for b in briefs:
        title = b["title"].replace("|", "\\|")
        lines.append(f"| `{b['id']}` | {b['state']} | {b['complexity']} | {title} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", type=int, choices=[1, 2, 3, 4])
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    text = build_summary(repo, args.phase)
    out = repo / "docs" / "progress" / f"phase{args.phase}-summary.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"Wrote {out.relative_to(repo)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
