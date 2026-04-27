"""Validates YAML frontmatter on every brief in phase{1-4}-briefs/.

Checks:
1. Schema validation against phase1-briefs/_frontmatter-schema.yaml
2. id matches filename basename
3. depends_on entries reference existing briefs
4. No cycles in the depends_on graph

Returns a list of error strings; empty list = OK.
CLI: prints errors to stderr and exits 1 on any error.
"""
from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import frontmatter
import yaml
from jsonschema import Draft202012Validator


def _iter_briefs(repo_root: Path) -> Iterator[Path]:
    for phase in (1, 2, 3, 4):
        d = repo_root / f"phase{phase}-briefs"
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            if f.name.startswith("_"):
                continue
            yield f


def _load_schema(repo_root: Path) -> dict:
    schema_path = repo_root / "phase1-briefs" / "_frontmatter-schema.yaml"
    return yaml.safe_load(schema_path.read_text(encoding="utf-8"))


def _detect_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    """Tarjan-light: returns first cycle as a list of brief ids; empty if no cycle."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    cycles: list[list[str]] = []

    def visit(node: str, path: list[str]) -> None:
        if color[node] == GRAY:
            i = path.index(node)
            cycles.append(path[i:] + [node])
            return
        if color[node] == BLACK:
            return
        color[node] = GRAY
        for dep in graph.get(node, []):
            if dep in graph:
                visit(dep, path + [node])
                if cycles:
                    return
        color[node] = BLACK

    for n in graph:
        if cycles:
            break
        visit(n, [])
    return cycles


def validate_repo(repo_root: Path) -> list[str]:
    """Run all frontmatter checks. Returns list of error messages."""
    errors: list[str] = []
    schema = _load_schema(repo_root)
    validator = Draft202012Validator(schema)

    briefs: dict[str, dict] = {}

    for path in _iter_briefs(repo_root):
        try:
            doc = frontmatter.load(path)
        except Exception as e:
            errors.append(f"{path.name}: parse error: {e}")
            continue
        meta = dict(doc.metadata)
        if not meta:
            errors.append(f"{path.name}: missing frontmatter")
            continue
        for err in sorted(validator.iter_errors(meta), key=lambda e: e.path):
            field = ".".join(str(p) for p in err.path) or "<root>"
            errors.append(f"{path.name}: schema: {field}: {err.message}")
        expected_id = path.stem
        if meta.get("id") != expected_id:
            errors.append(f"{path.name}: id mismatch (filename={expected_id}, frontmatter id={meta.get('id')})")
        briefs[meta.get("id", path.stem)] = meta

    all_ids = set(briefs.keys())
    for bid, meta in briefs.items():
        for dep in meta.get("depends_on") or []:
            if dep not in all_ids:
                errors.append(f"{bid}: depends_on points to non-existent brief: {dep}")
        for blk in meta.get("blocks") or []:
            if blk not in all_ids:
                errors.append(f"{bid}: blocks points to non-existent brief: {blk}")

    graph = {bid: meta.get("depends_on") or [] for bid, meta in briefs.items()}
    cycles = _detect_cycles(graph)
    for cyc in cycles:
        errors.append(f"cycle in depends_on: {' -> '.join(cyc)}")

    return errors


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    errors = validate_repo(repo)
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        print(f"\n{len(errors)} validation error(s).", file=sys.stderr)
        return 1
    print("Frontmatter OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
