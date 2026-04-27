"""One-shot: lift `## Status` blocks from existing briefs into YAML frontmatter.

Behavior per brief file:
1. If frontmatter already exists -> no-op (idempotent).
2. Else: parse `## Status` section bullets, build frontmatter, prepend.
3. Remove the `## Status` section from the body (frontmatter is the new source).

Run once during bootstrap, then never again. The pre-commit
`validate_frontmatter.py` ensures consistency going forward.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml


_STATUS_RE = re.compile(
    r"##\s+Status\s*\n(.*?)(?=\n##\s+|\Z)",
    re.DOTALL | re.IGNORECASE,
)
_TITLE_RE = re.compile(r"##\s+Title\s*\n+([^\n]+)", re.IGNORECASE)
_AC_RE = re.compile(r"\bAC-\d{1,3}\b")


def _strip_parens(s: str) -> str:
    """Remove all parenthetical groups (incl. nested) from a string.

    `phase2-chains-001 (read adapter, get_logs, get_block_number)`
        -> `phase2-chains-001 `
    """
    prev = None
    cur = s
    while prev != cur:
        prev = cur
        cur = re.sub(r"\([^()]*\)", "", cur)
    return cur


def _clean_value(val: str) -> str:
    """Normalize a parsed bullet value: strip parens, backticks, brackets, bold."""
    # Strip ALL parenthetical commentary first (handles intra-list parens).
    val = _strip_parens(val)
    # Strip backticks throughout.
    val = val.replace("`", "")
    # Strip `**bold**` markdown emphasis.
    val = re.sub(r"\*\*", "", val)
    # Unwrap surrounding [ ] list brackets if present.
    val = re.sub(r"^\s*\[\s*(.*?)\s*\]\s*$", r"\1", val).strip()
    return val.strip()


def _bullet_value(block: str, key: str) -> str | None:
    """Extract the value following `- **<key>:** ...` (case-insensitive).

    Aggressively normalizes: strips backticks, brackets, bold markers, and ALL
    parenthetical commentary (e.g. `phase1-shared-003 (UoW)` or
    `phase2-chains-001 (read adapter, get_logs, get_block_number)`).
    Returns "" for sentinel "none"-like values.
    """
    pattern = re.compile(
        rf"-\s*\*\*{re.escape(key)}:?\*\*[\s:]*(.+?)(?:\n|$)",
        re.IGNORECASE,
    )
    m = pattern.search(block)
    if not m:
        return None
    val = _clean_value(m.group(1).strip())
    # Sentinel "none"-equivalents.
    if val.lower() in {"(none)", "n/a", "none", "-", "", "none.", "none new", "none new."}:
        return ""
    if val.lower().startswith("none ") or val.lower().startswith("none."):
        return ""
    return val


def _csv_list(s: str | None) -> list[str]:
    if not s:
        return []
    items: list[str] = []
    for raw in re.split(r"[,;]", s):
        item = _clean_value(raw.strip())
        item = item.strip("[]").strip()
        if item:
            items.append(item)
    return items


def parse_status_section(body: str, brief_id: str) -> dict:
    m = _STATUS_RE.search(body)
    block = m.group(1) if m else ""
    title_m = _TITLE_RE.search(body)
    title = title_m.group(1).strip() if title_m else brief_id

    ac_count = len(set(_AC_RE.findall(body)))

    phase_str = _bullet_value(block, "Phase") or brief_id[5]
    estimated_str = _bullet_value(block, "Estimated") or "4h"
    estimated_match = re.search(r"\d+", estimated_str)

    raw_context = _bullet_value(block, "Context") or _infer_context_from_id(brief_id)
    context = _normalize_context(raw_context)

    raw_complexity = _bullet_value(block, "Complexity") or "M"
    complexity = _normalize_complexity(raw_complexity)

    raw_sdd = _bullet_value(block, "SDD mode") or "strict"
    sdd_mode = "lightweight" if "light" in raw_sdd.lower() else "strict"

    raw_state = _bullet_value(block, "State") or "ready"
    state = _normalize_state(raw_state)

    return {
        "id": brief_id,
        "phase": int(phase_str),
        "context": context,
        "title": title,
        "complexity": complexity,
        "sdd_mode": sdd_mode,
        "estimated_hours": int(estimated_match.group(0)) if estimated_match else 4,
        "state": state,
        "depends_on": _filter_brief_ids(_csv_list(_bullet_value(block, "Depends on"))),
        "blocks": _filter_brief_ids(_csv_list(_bullet_value(block, "Blocks"))),
        "touches_adrs": _filter_adr_ids(_csv_list(_bullet_value(block, "Touches ADRs"))),
        "ac_count": ac_count if ac_count >= 1 else 1,
    }


_VALID_CONTEXTS = {
    "identity", "kyc", "wallet", "custody", "chains", "ledger", "balances",
    "transactions", "contacts", "ai", "notifications", "pricing", "admin",
    "shared", "deploy", "web", "audit", "faucet",
}
_VALID_STATES = {"ready", "in_progress", "review", "merged", "blocked", "obsolete"}


def _normalize_context(raw: str) -> str:
    """Pick the first known-valid context token from the raw string."""
    if not raw:
        return "shared"
    lowered = raw.lower()
    # First token by whitespace/comma is usually the primary context.
    tokens = re.split(r"[\s,/+]+", lowered)
    for tok in tokens:
        cleaned = tok.strip(".:")
        if cleaned in _VALID_CONTEXTS:
            return cleaned
    # Fallback: first word.
    return tokens[0] if tokens else "shared"


def _normalize_complexity(raw: str) -> str:
    """Extract S/M/L from the raw complexity string."""
    upper = raw.upper().strip()
    for ch in upper:
        if ch in {"S", "M", "L"}:
            return ch
    return "M"


def _normalize_state(raw: str) -> str:
    lowered = raw.lower().strip().rstrip(".")
    # `in progress` -> `in_progress` etc.
    snake = re.sub(r"\s+", "_", lowered)
    if snake in _VALID_STATES:
        return snake
    return "ready"


_BRIEF_ID_RE = re.compile(r"^phase[1-4]-[a-z]+(?:-[a-z]+)*-[0-9]{3}$")
_ADR_ID_RE = re.compile(r"^ADR-[0-9]{3}$")


def _filter_brief_ids(items: list[str]) -> list[str]:
    """Keep only items that look like a valid brief id."""
    return [i for i in items if _BRIEF_ID_RE.match(i)]


def _filter_adr_ids(items: list[str]) -> list[str]:
    """Keep only items that look like a valid ADR id."""
    out: list[str] = []
    for it in items:
        # Pull a leading ADR-NNN token out if it exists.
        m = re.search(r"\bADR-\d{3}\b", it)
        if m:
            out.append(m.group(0))
    return out


def _infer_context_from_id(brief_id: str) -> str:
    """phase1-identity-002 -> identity"""
    parts = brief_id.split("-")
    return parts[1] if len(parts) >= 3 else "shared"


def _strip_status_section(body: str) -> str:
    return re.sub(_STATUS_RE, "", body, count=1).lstrip("\n")


def retrofit_brief(path: Path) -> bool:
    """Returns True if file was modified, False if no-op."""
    raw = path.read_text(encoding="utf-8")
    if raw.startswith("---"):
        return False
    brief_id = path.stem
    fields = parse_status_section(raw, brief_id)
    new_body = _strip_status_section(raw)
    fm_text = yaml.safe_dump(fields, sort_keys=False, allow_unicode=True)
    path.write_text(f"---\n{fm_text}---\n\n{new_body}", encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    modified: list[Path] = []
    skipped: list[Path] = []
    for phase in (1, 2, 3, 4):
        d = repo / f"phase{phase}-briefs"
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            if f.name.startswith("_"):
                continue
            if args.dry_run:
                raw = f.read_text(encoding="utf-8")
                if not raw.startswith("---"):
                    modified.append(f)
                else:
                    skipped.append(f)
            elif retrofit_brief(f):
                modified.append(f)
            else:
                skipped.append(f)
    print(f"{'Would modify' if args.dry_run else 'Modified'}: {len(modified)} brief(s)")
    print(f"Already had frontmatter: {len(skipped)} brief(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
