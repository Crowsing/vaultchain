---
name: self-review-pr
description: Verify the current PR satisfies the brief's Done Definition; post a PR comment if pass.
---

# Self-Review PR

## Step 1: Re-read

- Brief's `## Done Definition` section
- Brief's `## Acceptance Criteria` section
- Brief's `## Test Coverage Required` section

## Step 2: Verify each Done Definition item

For each item in Done Definition:
1. Find evidence in the diff (file changed, test added, doc updated).
2. If you cannot find evidence → return `fail` with the missing item.

## Step 3: Verify AC↔test mapping

For each `AC-NN`, confirm at least one test name references it. Ideal pattern: `test_ac_NN_*`.

If any AC has no corresponding test → return `fail` with the unmapped AC.

## Step 4: Architectural drift check

Run:
```bash
cd backend && poetry run lint-imports
```

If non-zero → return `fail` with "import-linter contract violation: <name>".

## Step 5: Post PR comment

If all checks pass:

```bash
gh pr comment --body "$(cat <<'EOF'
## Self-review

Done Definition checked, all ACs verified by named tests:
- AC-01 → test_ac_01_<name>
- AC-02 → test_ac_02_<name>
- ... (full list)

No architectural drift (`lint-imports` green).

This comment is the merge gate per project convention. Branch protection requires green CI; auto-merge will fire once CI passes.
EOF
)"
```

Return `pass`.

## Return value

- `pass` — comment posted, ready for auto-merge.
- `fail` — return string with specific reason.
