"""Adapter-style tests for `scripts/generate_errors_reference.py`.

Covers AC-phase1-shared-005-08: one section per concrete subclass, idempotency
on rerun, and that the human Meaning comes from the class docstring.

The script does not live under `vaultchain.*` so we import it via spec
loading. Tests use the `render()` helper rather than driving the CLI so we
don't hit disk on every assertion.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_errors_reference.py"


def _load_script_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_errors_reference_generator", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_generator_produces_one_section_per_subclass() -> None:
    """One H2 section per concrete code; no section for the abstract base."""
    mod = _load_script_module()
    rendered = mod.render()

    from vaultchain.shared.domain.errors import DomainError

    concrete = [
        cls
        for cls in mod._walk_subclasses(DomainError)  # type: ignore[attr-defined]
        if cls.code
    ]
    h2_lines = [line for line in rendered.splitlines() if line.startswith("## ")]
    assert len(h2_lines) == len(concrete) > 0
    for cls in concrete:
        assert f"## `{cls.code}`" in rendered


def test_generator_is_idempotent() -> None:
    mod = _load_script_module()
    first = mod.render()
    second = mod.render()
    assert first == second


def test_generator_uses_class_docstring_for_meaning() -> None:
    """Meaning line comes from the first line of the class docstring."""
    mod = _load_script_module()
    rendered = mod.render()
    # ValidationError.__doc__ → "Inputs failed validation — wrong shape, type, or basic semantics."
    assert "Inputs failed validation" in rendered


def test_check_mode_succeeds_on_in_sync_file(tmp_path: Path, monkeypatch: object) -> None:
    """`--check` returns 0 when the rendered output equals the file on disk."""
    mod = _load_script_module()
    rendered = mod.render()

    target = tmp_path / "docs" / "errors-reference.md"
    target.parent.mkdir(parents=True)
    target.write_text(rendered, encoding="utf-8")

    # Patch OUTPUT_PATH to a relative path under our fake repo root, then
    # patch Path-resolve so the script picks tmp_path as the repo root.
    real_resolve = Path.resolve

    def _fake_resolve(self: Path, *args: object, **kwargs: object) -> Path:
        if self == Path(SCRIPT_PATH):
            return tmp_path / "scripts" / "generate_errors_reference.py"
        return real_resolve(self, *args, **kwargs)  # type: ignore[arg-type]

    # Use monkeypatch from pytest. Reannotate to avoid the loose `object` type.
    import pytest

    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(Path, "resolve", _fake_resolve)
        mp.setattr(sys, "argv", ["generate_errors_reference.py", "--check"])
        rc = mod.main()
    finally:
        mp.undo()
    assert rc == 0
