"""Per-directory coverage threshold enforcement.

Reads a coverage.xml in cobertura format (produced by `pytest --cov-report=xml`)
and asserts that each declared directory meets its threshold.

Thresholds (per spec §7.1):
    vaultchain.shared.domain                                 95%
    vaultchain.{ledger,custody,transactions,chains}.domain   95%
    vaultchain.*.domain                                      90%
    vaultchain.*.application                                 85%
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

CRITICAL_DOMAINS = {"ledger", "custody", "transactions", "chains"}
OTHER_CONTEXTS = {
    "identity", "kyc", "wallet", "balances", "contacts",
    "notifications", "pricing", "ai", "admin",
}


def _thresholds() -> dict[str, float]:
    t: dict[str, float] = {"vaultchain.shared.domain": 0.95}
    for ctx in CRITICAL_DOMAINS:
        t[f"vaultchain.{ctx}.domain"] = 0.95
    for ctx in OTHER_CONTEXTS:
        t[f"vaultchain.{ctx}.domain"] = 0.90
    for ctx in CRITICAL_DOMAINS | OTHER_CONTEXTS:
        t[f"vaultchain.{ctx}.application"] = 0.85
    return t


def check_thresholds(coverage_xml: Path) -> tuple[int, list[str]]:
    if not coverage_xml.exists():
        return 2, [f"coverage.xml not found at {coverage_xml}"]
    tree = ET.parse(coverage_xml)
    rates: dict[str, float] = {}
    for pkg in tree.iterfind(".//package"):
        name = pkg.get("name")
        rate = pkg.get("line-rate")
        if name and rate is not None:
            rates[name] = float(rate)
    errors: list[str] = []
    for pkg, threshold in _thresholds().items():
        if pkg not in rates:
            # Phase 1 may not yet have created every context's domain code.
            # We tolerate missing packages; only enforce the threshold when present.
            continue
        actual = rates[pkg]
        if actual < threshold:
            errors.append(
                f"{pkg}: {actual:.2f} below threshold {threshold:.2f} "
                f"({(threshold - actual) * 100:.1f}pp short)"
            )
    return (1 if errors else 0), errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "coverage_xml",
        nargs="?",
        type=Path,
        default=Path("coverage.xml"),
        help="path to coverage.xml (default: ./coverage.xml)",
    )
    args = parser.parse_args()
    rc, errors = check_thresholds(args.coverage_xml)
    for e in errors:
        print(e, file=sys.stderr)
    if errors:
        print(f"\n{len(errors)} threshold violation(s).", file=sys.stderr)
    else:
        print("Coverage thresholds OK.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
