"""Generate docs/briefs/manifest.yaml and dependency-graph.mmd from brief frontmatter.

The manifest is the projection of:
- docs/briefs/phase_pointer.yaml  (current_phase, phase_state — hand-mutable)
- ALL phase{1-4}-briefs/*.md frontmatter (state, deps, etc — per-brief)

CLI usage:
    python scripts/gen_manifest.py             # writes manifest.yaml + .mmd
    python scripts/gen_manifest.py --check     # exit 1 if committed manifest drifts
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import frontmatter
import yaml

MANIFEST_PATH = Path("docs/briefs/manifest.yaml")
MERMAID_PATH = Path("docs/briefs/dependency-graph.mmd")
PHASE_POINTER_PATH = Path("docs/briefs/phase_pointer.yaml")


def _iter_briefs(repo_root: Path) -> Iterator[Path]:
    for phase in (1, 2, 3, 4):
        d = repo_root / f"phase{phase}-briefs"
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            if f.name.startswith("_"):
                continue
            yield f


def _load_phase_pointer(repo_root: Path) -> dict:
    pp = repo_root / PHASE_POINTER_PATH
    if not pp.exists():
        return {"current_phase": 1, "phase_state": "in_progress"}
    return yaml.safe_load(pp.read_text(encoding="utf-8")) or {}


def generate_manifest(repo_root: Path) -> dict:
    """Build manifest as a Python dict."""
    pointer = _load_phase_pointer(repo_root)
    briefs: list[dict] = []
    for path in _iter_briefs(repo_root):
        meta = dict(frontmatter.load(path).metadata)
        if not meta:
            continue
        briefs.append(
            {
                "id": meta["id"],
                "phase": meta["phase"],
                "context": meta["context"],
                "title": meta["title"],
                "complexity": meta["complexity"],
                "sdd_mode": meta["sdd_mode"],
                "state": meta["state"],
                "depends_on": list(meta.get("depends_on") or []),
                "blocks": list(meta.get("blocks") or []),
                "touches_adrs": list(meta.get("touches_adrs") or []),
                "ac_count": meta["ac_count"],
                "estimated_hours": meta.get("estimated_hours"),
                "path": str(path.relative_to(repo_root)),
            }
        )
    briefs.sort(key=lambda b: (b["phase"], b["id"]))

    by_state = Counter(b["state"] for b in briefs)
    by_phase = Counter(b["phase"] for b in briefs)
    by_context = Counter(b["context"] for b in briefs)

    return {
        "current_phase": pointer.get("current_phase", 1),
        "phase_state": pointer.get("phase_state", "in_progress"),
        "counts": {
            "total": len(briefs),
            "by_state": dict(sorted(by_state.items())),
            "by_phase": dict(sorted(by_phase.items())),
            "by_context": dict(sorted(by_context.items())),
        },
        "briefs": briefs,
    }


def generate_mermaid(repo_root: Path) -> str:
    """Build a mermaid flowchart of brief dependency graph."""
    manifest = generate_manifest(repo_root)
    lines = ["graph LR", "  classDef ready fill:#dbeafe;", "  classDef merged fill:#bbf7d0;",
             "  classDef in_progress fill:#fef3c7;", "  classDef blocked fill:#fecaca;",
             "  classDef review fill:#e9d5ff;"]
    for b in manifest["briefs"]:
        node_id = b["id"].replace("-", "_")
        label = f"{b['id']}<br/>{b['title'][:40]}"
        lines.append(f'  {node_id}["{label}"]:::{b["state"]}')
    for b in manifest["briefs"]:
        nid = b["id"].replace("-", "_")
        for dep in b["depends_on"]:
            dep_id = dep.replace("-", "_")
            lines.append(f"  {dep_id} --> {nid}")
    return "\n".join(lines) + "\n"


def write_outputs(repo_root: Path) -> None:
    manifest = generate_manifest(repo_root)
    mmd = generate_mermaid(repo_root)
    (repo_root / MANIFEST_PATH).parent.mkdir(parents=True, exist_ok=True)
    (repo_root / MANIFEST_PATH).write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8",
    )
    (repo_root / MERMAID_PATH).write_text(mmd, encoding="utf-8")


def run_check(repo_root: Path) -> int:
    """Return 0 if committed manifest matches generated; 1 if drift."""
    expected = generate_manifest(repo_root)
    committed_path = repo_root / MANIFEST_PATH
    if not committed_path.exists():
        print("ERROR: docs/briefs/manifest.yaml is missing.", file=sys.stderr)
        return 1
    committed = yaml.safe_load(committed_path.read_text(encoding="utf-8")) or {}
    if committed != expected:
        print(
            "ERROR: docs/briefs/manifest.yaml is stale.\n"
            "Run `python scripts/gen_manifest.py` to regenerate.",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="exit 1 if committed manifest drifts")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    if args.check:
        return run_check(repo)
    write_outputs(repo)
    print("Manifest written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
