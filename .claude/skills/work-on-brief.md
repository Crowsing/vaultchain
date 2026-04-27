---
name: work-on-brief
description: Implement ONE brief end-to-end with TDD per AC, then open PR with self-review. Returns success | needs-iteration | blocked.
---

# Work on Brief

Argument: `<brief-id>` (e.g., `phase2-custody-001`).

## Step 1: Read the brief + linked ADRs

1. Read `phase{N}-briefs/<brief-id>.md` fully.
2. For each `ADR-XXX` in `touches_adrs`, read that section of `docs/architecture-decisions.md`.
3. If brief is in a context with a design spec (`specs/0X-*.md`), read it.

## Step 2: Plan

Enumerate every `AC-NN` in the brief's `## Acceptance Criteria`. For each:
- Identify the test file path (`backend/tests/<context>/test_<feature>.py`).
- Identify the test name (`test_ac_NN_<short_description>`).
- Identify which layer (delivery/application/domain/infra) the implementation touches.

If `ac_count` in frontmatter mismatches what you find, halt with `blocked` (frontmatter drift = signal to investigate).

## Step 3: TDD per AC

For each AC in declared order:

1. **Write failing test.** Use scenarios from the brief's `## Test Coverage Required` section.
2. **Run.** `cd backend && poetry run pytest tests/<context>/test_<feature>.py::test_ac_NN_* -v`. Confirm RED.
3. **Implement.** Minimum code to pass. Layer order: domain → application → infra → delivery.
4. **Run.** Confirm GREEN.
5. **Refactor** if obvious cleanup is needed. Re-run GREEN.

## Step 4: Cross-cutting checks (after all ACs)

```bash
cd backend
poetry run ruff check . --fix
poetry run ruff format .
poetry run mypy src/vaultchain
poetry run lint-imports
poetry run pytest --cov=src/vaultchain --cov-report=term-missing
python ../scripts/check_coverage.py
```

If any fails: fix in-place, re-run. If you cannot fix in 2 attempts → return `blocked`.

## Step 5: API contract sync (if API changed)

If the brief touches FastAPI routes:
```bash
python scripts/generate_openapi.py
git diff docs/api-contract.yaml
```

If `shared-types/` is consumed by a brief, regenerate TS types via the brief's stated codegen command.

## Step 6: Commit + PR

```bash
git add -A
git commit -m "feat(<context>): <title> [<brief-id>]"
git push origin feature/<brief-id>
gh pr create --fill --template <(cat .github/PULL_REQUEST_TEMPLATE.md)
```

## Step 7: Self-review

Invoke `/self-review-pr`. If it returns `pass`, return `success`. If `fail`, fix the failing item and re-run from Step 3. If second failure → return `needs-iteration`.

## Return value

- `success` — PR opened with self-review-comment posted, auto-merge enabled.
- `needs-iteration` — CI failed; caller (`autonomous-build`) handles retry.
- `blocked` — unrecoverable; caller invokes `/enter-blocked-state`.
