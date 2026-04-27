# VaultChain — Claude Code Project Memory

You are Claude Code working on VaultChain inside an autonomous `/loop` loop.
Read this file at the start of EVERY cycle (the `/sync-architecture` skill enforces it).

## Invariants (NEVER violate; from `docs/architecture-decisions.md`)

1. **Custody is sacred.** AI never imports `vaultchain.custody`. Enforced by import-linter contract "AI never imports Custody".
2. **Money is `Decimal`/`NUMERIC(78,0)`.** Never `float`, never `int` for amounts. Quantize per chain decimals.
3. **Sessions are opaque tokens.** Never JWT. 256-bit random in Redis with TTL.
4. **Real double-entry ledger.** Every value movement = 1 `entries` row + ≥2 `postings`. Sum of postings per entry = 0.
5. **Outbox + idempotency.** Every external call goes through outbox; every state change has both Redis SET NX EX 86400 + DB UNIQUE constraint.
6. **Never execute, only prepare.** AI surfaces `PreparedAction` (ADR-011); user confirms in deterministic UI; broadcast goes through Custody.

## Loop discipline

- **TDD.** Write failing test first. Run it red. Implement. Run green. Refactor. Commit.
- **One AC at a time.** Don't batch ACs into one giant commit.
- **Conventional commits.** `feat(<context>): <title> [<brief-id>]`, `chore: …`, `test: …`, `docs: …`.
- **Branch naming.** `feature/<brief-id>` (e.g. `feature/phase2-custody-001`).
- **Max 2 CI iterations per brief.** 3rd failure → `/enter-blocked-state` and halt.
- **PR self-review is the merge gate.** Auto-merge requires both green CI AND a `/self-review-pr` comment.

## ADR conflict handling

If a brief contradicts `docs/architecture-decisions.md`:
1. Stop work.
2. Write the conflict into `phase{N}-briefs/blocked/<brief-id>.md`.
3. Mark brief `state: blocked`.
4. Push, then halt the loop. Telegram notifies the operator.

## Forbidden actions

- `git push --force` / `--force-with-lease`
- `git commit --no-verify`
- `pip install <pkg>` outside Poetry (use `poetry add`)
- `# type: ignore` without an attached `# pragma: <reason>` justification
- Hand-editing `docs/briefs/manifest.yaml` (it's auto-generated)
- Modifying tests to make them pass instead of fixing the implementation
- Skipping pre-commit hooks
- Writing to `.env*` or `**/secrets/**`

## Precedence rules (when sources conflict)

1. `docs/architecture-decisions.md` — authoritative for technical contracts
2. `specs/claude-code-spec.md` — authoritative for API/data model details
3. `specs/claude-design-spec.md` — authoritative for visual/UX
4. `specs/0X-*.md` — authoritative for individual flow contracts
5. Brief content — implementation-level details
6. `*-notes.md` files — supporting context

If 1+ conflict with each other, ADR wins, and you write a new ADR section explaining the resolution before implementing.

## Slash commands the operator uses

- `/approve-phase <N>` — open phase N for work (user runs after reviewing summary)
- `/unblock-brief <id>` — clear blocked state after the operator fixed the input
- `/status` — print snapshot of current state

## Session etiquette

- Always run `/sync-architecture` at the start of a cycle.
- Always invoke `/autonomous-build` (the main skill) per cycle. One brief per invocation.
- Never delete brief files except on explicit operator request.
- Use `ScheduleWakeup` to self-pace: 60s after merge (next brief), 120s while CI running, 1800s when blocked or awaiting phase approval, 60s when idle.
