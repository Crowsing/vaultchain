"""Build docs/errors-reference.md from exception classes in vaultchain.shared.errors.

Phase 1 brief phase1-shared-006 finalizes this. Stub follows the same shape as
generate_openapi.py — exits 0 in both modes until the source classes exist.
"""
from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.parse_args()
    print("Errors reference skipped (no exception classes yet — phase1-shared-006 wires this).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
