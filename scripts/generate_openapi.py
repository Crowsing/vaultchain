"""Build docs/api-contract.yaml from FastAPI's generated OpenAPI schema.

Phase 1 brief phase1-shared-005 finalizes this. For bootstrap we provide a
stub that exits 0 in normal mode (write) and 0 in --check mode if the file
already exists, so CI doesn't fail before any routes exist.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    contract = repo / "docs" / "api-contract.yaml"
    if args.check:
        if not contract.exists():
            print("docs/api-contract.yaml missing", file=sys.stderr)
            return 1
        print("OpenAPI drift check skipped (no routes yet — phase1-shared-005 wires this).")
        return 0
    print("OpenAPI generation skipped (no routes yet — phase1-shared-005 wires this).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
