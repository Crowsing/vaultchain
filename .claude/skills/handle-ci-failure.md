---
name: handle-ci-failure
description: Diagnose and fix CI failure on the current branch (max 2 iterations per brief).
---

# Handle CI Failure

## Step 1: Find the failed run

```bash
gh run list --branch $(git rev-parse --abbrev-ref HEAD) --limit 1 --json databaseId,conclusion,headSha
RUN_ID=<from json>
```

## Step 2: Read failure logs

```bash
gh run view $RUN_ID --log-failed > /tmp/ci-failure.log
head -200 /tmp/ci-failure.log
```

## Step 3: Diagnose

Categorize:
- **Lint** (ruff/eslint) → fix style.
- **Type** (mypy/tsc) → fix annotation.
- **Test** (pytest/vitest) → fix code (NEVER modify the test to pass).
- **Coverage** (`scripts/check_coverage.py`) → add tests.
- **Architectural** (import-linter) → restructure to respect contract.
- **Frontmatter** (validate_frontmatter.py) → fix YAML.
- **Manifest drift** → run `python scripts/gen_manifest.py` and commit.

## Step 4: Fix locally

Make the minimum change to address the failure.

## Step 5: Re-test locally

```bash
cd backend && poetry run pytest && poetry run mypy src/vaultchain && poetry run lint-imports
```

If still failing after 30 min → return `blocked`.

## Step 6: Push

```bash
git add -A
git commit -m "fix: <category>: <one-line description>"
git push
```

## Iteration cap

This skill tracks iteration count per branch via the commit log: count commits matching `^fix: .*$` on the current branch. If count ≥ 2 → return `blocked` instead of pushing. The caller (`autonomous-build`) escalates to `/enter-blocked-state`.

## Return value

- `success` — pushed, expect green CI on next run.
- `blocked` — exceeded iteration cap or unable to diagnose.
