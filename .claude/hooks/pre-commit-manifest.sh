#!/usr/bin/env bash
# Auxiliary helper invoked by .pre-commit-config.yaml local hook.
# Regenerates manifest if any brief or phase_pointer changed.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

CHANGED=$(git diff --cached --name-only)
if echo "$CHANGED" | grep -qE '^(phase[1-4]-briefs/|docs/briefs/phase_pointer\.yaml)'; then
  echo "[pre-commit-manifest] regenerating manifest..."
  python scripts/gen_manifest.py
  git add docs/briefs/manifest.yaml docs/briefs/dependency-graph.mmd
fi
