# SDD + DDD + TDD Infrastructure for Autonomous Claude Code Build — Design Spec

**Status:** approved (brainstorm phase complete; awaiting user review of this spec) · **Date:** 2026-04-27 · **Author:** brainstorming session with Claude Opus 4.7 (1M context)

---

## 1. Goal

Bootstrap the VaultChain repository so Claude Code can autonomously execute the 67 existing briefs (across 4 phases) with minimal user intervention. The user steers only at phase milestones; Claude Code runs the SDD loop end-to-end inside each phase.

This spec defines:
- Repo skeleton (backend + frontend + infra placeholders)
- Brief frontmatter schema and manifest auto-generation pipeline
- `.claude/` orchestration layer (skills, slash commands, hooks)
- CI/CD pipelines (8-stage backend, frontend, deploy, notifications)
- Test infrastructure (testcontainers, hypothesis profiles, coverage gates)
- Architectural enforcement (import-linter contracts, mypy strict)
- Bootstrap runbook (operator-side provisioning before launch)
- Day-1 launch sequence

The terminal output is a `git commit` containing all scaffolding, after which the user runs `claude` locally with `/loop /autonomous-build` and the autonomous build begins from `phase1-shared-003`.

## 2. Brainstorming choices (locked)

| Decision | Choice | Rationale |
|---|---|---|
| Bootstrap scope | **A — All-on-host.** I create everything; user just provisions external services and pushes. | Maximum autonomy; user said "майже без втручання". |
| Runtime for autonomous loop | **A — local `/loop`.** Long-running `claude` session on user's machine. | Costs included in user's Claude subscription; full local control; easy to interrupt. |
| Manifest source of truth | **1 — frontmatter-first.** YAML frontmatter on every brief, manifest auto-generated. | Industry-standard, robust parser, briefs self-documenting. ADR §6 mandates auto-generation. |
| Auto-merge mechanism | `gh pr merge --auto --squash` after Claude self-review comment | Native GitHub flow, less workflow code. |
| Branch protection | Required PR + required status checks + dismiss stale + no force-push to main | Standard discipline. |
| `mypy --strict` scope | Global (entire `backend/src/vaultchain`) | ADR §5 mandate. |
| License | MIT | User confirmed. |
| Domain | placeholder `<USER_DOMAIN>` until registered; `phase1-deploy-001` fills | User has not yet registered. |
| Admin SPA path | `apps/admin/` (pnpm workspace) | User confirmed; pairs cleanly with workspace organisation. |
| `ac_count` in frontmatter | Yes (drift-check guard) | Tiny field, useful, default-on. |
| `property_tests` in frontmatter | No (parse from body during self-review) | Avoid duplication with `## Test Coverage Required`. |
| Merged-state transition | GH workflow callback (`manifest-on-merge.yml`) | Atomic, no extra Claude PR. |

## 3. Repository structure

```
vaultchain/                                     # the existing dir; we add into it
├── .git/                                        # `git init`, no remote at first
├── .gitignore .gitattributes .editorconfig
├── .python-version (3.12) .nvmrc (20.11)
├── README.md                                    # project overview + links to ADR/specs/briefs
├── LICENSE                                      # MIT
├── Makefile                                     # setup/dev/test/format/lint/seed-demo
├── pnpm-workspace.yaml                          # workspaces: web, apps/admin, shared-types
├── package.json                                 # root, dev tooling
├── docker-compose-dev.yml                       # postgres+pgvector, redis, mailhog,
│                                                # localstack(KMS), anvil; solana via profile
├── Dockerfile                                   # multi-stage backend deploy image
├── fly.toml                                     # placeholder; phase1-deploy-001 fills it
├── .pre-commit-config.yaml                      # ruff, mypy, import-linter, manifest-gen,
│                                                # openapi-drift, frontmatter-validator
├── BOOTSTRAP-RUNBOOK.md                         # operator-side setup before /loop
│
├── backend/                                     # empty skeleton; phase1 fills
│   ├── pyproject.toml                           # poetry, ruff, mypy --strict, import-linter
│   │                                            # contracts (the 4 from ADR §2 already declared),
│   │                                            # pytest (asyncio_mode=auto, hypothesis profile),
│   │                                            # coverage gates (95% domain, 85% global)
│   ├── src/vaultchain/__init__.py
│   ├── src/vaultchain/main.py                   # FastAPI app factory STUB (returns app)
│   ├── src/vaultchain/config.py                 # Pydantic Settings with all expected env vars
│   ├── src/vaultchain/shared/{domain,events,unit_of_work}/__init__.py
│   ├── src/vaultchain/{identity,kyc,wallet,custody,chains,ledger,balances,
│   │   transactions,contacts,ai,notifications,pricing,admin}/__init__.py
│   ├── alembic.ini · alembic/env.py · alembic/versions/  (empty)
│   ├── tests/architecture/test_layering.py      # runs import-linter
│   └── tests/conftest.py                        # session-scoped fixtures
│
├── web/                                         # Vite+React+TS, tokens.css imported
│   ├── package.json index.html src/main.tsx vite.config.ts tailwind.config.ts
│   └── public/
│
├── apps/admin/                                  # separate Vite app, same tokens
│   ├── package.json index.html src/main.tsx vite.config.ts
│   └── public/
│
├── shared-types/                                # generated from docs/api-contract.yaml
│   ├── package.json index.d.ts (placeholder)
│
├── infra/terraform/                             # phase 2+ filled; placeholder README
├── cli/scripts/                                 # seed_admin.py stub
│
├── docs/
│   ├── architecture-decisions.md                # already exists
│   ├── brief-template.md                        # already exists
│   ├── api-contract.yaml                        # placeholder OpenAPI 3.1
│   ├── data-model.md · runbook.md · security-model.md  (stubs with TODO)
│   ├── briefs/manifest.yaml                     # AUTO-GEN from frontmatter (initial empty)
│   ├── briefs/dependency-graph.mmd              # AUTO-GEN
│   ├── progress/phase1-log.md                   # auto-appended by manifest-on-merge
│   ├── decisions/                               # ADR-001..007 stubs from ADR §index
│   └── superpowers/specs/2026-04-27-sdd-infrastructure-design.md  # this file
│
├── phase{1-4}-briefs/                           # already exist; YAML frontmatter retrofit
│   └── _frontmatter-schema.yaml                 # JSON Schema for CI validation
│
├── .claude/
│   ├── settings.json                            # project-wide allow/deny
│   ├── settings.local.json                      # already exists (user-local)
│   ├── CLAUDE.md                                # project memory: invariants, loop rules, taboos
│   ├── skills/
│   │   ├── autonomous-build.md                  # MAIN — processes ONE brief per invocation
│   │   ├── sync-architecture.md                 # reads ADR + last 3 progress entries
│   │   ├── work-on-brief.md                     # internal — TDD per AC, layered impl
│   │   ├── self-review-pr.md                    # Done Definition checklist + PR comment
│   │   ├── handle-ci-failure.md                 # gh run view → fix → push (max 2x)
│   │   └── enter-blocked-state.md               # BLOCKED.md + Telegram + halt
│   ├── commands/
│   │   ├── approve-phase.md                     # /approve-phase 2 → mutates manifest
│   │   ├── unblock-brief.md                     # /unblock-brief <id> → ready
│   │   └── status.md                            # /status → snapshot manifest+log
│   └── hooks/
│       └── pre-commit-manifest.sh               # invokes scripts/gen_manifest.py
│
├── scripts/
│   ├── gen_manifest.py                          # frontmatter → manifest.yaml + .mmd
│   ├── validate_frontmatter.py                  # CI gate
│   ├── transition_brief_state.py                # CLI helper for state edits
│   ├── generate_errors_reference.py             # builds errors-reference.md (ADR §4)
│   ├── generate_openapi.py                      # builds api-contract.yaml from FastAPI
│   ├── phase_summary.py                         # phase exit checklist generator
│   └── check_coverage.py                        # per-directory threshold enforcement
│
└── .github/
    ├── workflows/
    │   ├── ci-backend.yml                       # 8-stage per ADR §5
    │   ├── ci-frontend.yml                      # lint + tsc + build + vitest
    │   ├── deploy.yml                           # main → fly + cloudflare pages
    │   ├── manifest-on-merge.yml                # PR merged → state=merged + commit
    │   ├── notify-blocked.yml                   # Telegram on `blocked` state
    │   ├── notify-phase-complete.yml            # Telegram on phase exit
    │   └── openapi-drift.yml                    # contract sync check
    ├── PULL_REQUEST_TEMPLATE.md                 # AC↔test mapping section
    └── ISSUE_TEMPLATE/
```

**Notes on key choices:**

- `backend/` is an EMPTY skeleton: app factory stub, `config.py` enumerating all expected env vars, and `__init__.py` for all 13 contexts. Phase 1 briefs (shared-003 onward) implement the actual code. This satisfies the "phase1-shared-001 + phase1-shared-002 pre-completed in bootstrap" claim from `PHASE1-SUMMARY.md`.
- `docker-compose-dev.yml` runs locally: `make dev` boots backend + both SPAs + emulators. Anvil session-scoped from Phase 2; Solana validator opt-in via compose profile from Phase 3 (heavy image).
- Pre-commit hook regenerates manifest on every brief edit. CI blocks merge if manifest is hand-edited (it must derive from frontmatter).
- Branches: `feature/<brief-id>` (e.g. `feature/phase1-identity-002`). Auto-merge to `main` after CI green + Claude self-review comment.

## 4. Brief frontmatter + manifest pipeline

### 4.1 Frontmatter schema

```yaml
---
id: phase1-identity-002                  # unique; matches file basename
phase: 1                                  # 1..4
context: identity                         # one of 13 contexts + shared/admin/deploy
title: "Magic-link signup/login + console email adapter"
complexity: L                             # S | M | L (XL forbidden)
sdd_mode: strict                          # strict | lightweight
estimated_hours: 6                        # author estimate, used in metrics
state: ready                              # ready | in_progress | review | merged | blocked | obsolete
depends_on:
  - phase1-identity-001
  - phase1-shared-003
blocks:
  - phase1-identity-005
touches_adrs:
  - ADR-002
  - ADR-003
ac_count: 11                              # CI guard against silent AC drift after claim
---
```

### 4.2 Pre-commit hook

`.pre-commit-config.yaml` runs on every commit that touches `phase*-briefs/*.md` or `scripts/gen_manifest.py`:

- `validate_frontmatter.py` — schema checks (id matches filename; depends_on briefs exist; cycles forbidden; complexity in S|M|L; sdd_mode in strict|lightweight; for strict mode `ac_count >= 1`).
- `gen_manifest.py` — regenerates `docs/briefs/manifest.yaml` and `docs/briefs/dependency-graph.mmd` from frontmatter.

### 4.3 State machine

| Transition | Trigger | Mutator |
|---|---|---|
| `(initial) → ready` | bootstrap | human authoring |
| `ready → in_progress` | claim | `/autonomous-build` skill (commit + push branch) |
| `in_progress → review` | PR opened | `/work-on-brief` skill after `gh pr create` |
| `review → merged` | auto-merge fired | GH workflow `manifest-on-merge.yml` |
| `* → blocked` | 2 CI fails OR ADR conflict | `/enter-blocked-state` skill |
| `blocked → ready` | human after fix | `/unblock-brief <id>` slash command |
| `* → obsolete` | brief deleted/superseded | manual edit + commit |

**Per-brief state** lives in brief frontmatter only. `manifest.yaml` projects it (regenerated). One source of truth per ADR §6.

**Phase-level pointer** (which phase the loop should consume from) is a SEPARATE small file `docs/briefs/phase_pointer.yaml` (~3 lines: `current_phase`, `phase_state`). This file is the only manually-mutated input to manifest generation; `gen_manifest.py` reads it plus all brief frontmatter and produces `manifest.yaml`. Mutators of `phase_pointer.yaml`:
- bootstrap → `current_phase: 1`, `phase_state: in_progress`
- `/autonomous-build` (auto-detected last brief in phase merged) → `phase_state: awaiting_{N+1}_approval`
- `/approve-phase <N>` slash command → `current_phase: <N>`, `phase_state: in_progress`
- `gen_manifest.py` post-Phase-4 → `phase_state: complete` (derived; not human-mutated)

Splitting phase pointer from manifest preserves the "manifest is fully auto-generated" invariant — manifest is `phase_pointer.yaml ∪ frontmatter projection`, and only `phase_pointer.yaml` ever gets hand-edited (or `/approve-phase` mutated).

### 4.4 CI gates

`ci-backend.yml` Stage 1 includes:
```bash
python scripts/validate_frontmatter.py
python scripts/gen_manifest.py --check    # exits non-zero if manifest drifts from frontmatter
```

`--check` mode generates manifest into a tmp file and diffs it against the committed `manifest.yaml`. Drift fails CI with "manifest stale, run pre-commit hook".

### 4.5 Initial frontmatter retrofit (one-shot)

I will pass over all 67 briefs and lift fields from each `## Status` section into YAML frontmatter, then DELETE the `## Status` section from the body (frontmatter becomes the single source). `ac_count` derives from counting `AC-*-NN:` IDs in `## Acceptance Criteria`.

## 5. `.claude/` orchestration — autonomous build skill

### 5.1 `/autonomous-build` (main loop, `.claude/skills/autonomous-build.md`)

One invocation = one brief processed. `/loop /autonomous-build` (no interval) lets the model self-pace via `ScheduleWakeup`.

Algorithm:
```
1.  Read .claude/CLAUDE.md (invariants reminder).
2.  /sync-architecture (ADR + 3 last log entries → working memory).
3.  manifest = yaml.load("docs/briefs/manifest.yaml")
4.  Branch on phase_state:
        awaiting_N_approval → ScheduleWakeup(1800, "phase-gate awaits user"); halt
        complete → halt loop permanently (Telegram "🎉 V1 complete")
        in_progress → continue
5.  ready = [b for b in briefs if state=='ready'
            and all(d.state=='merged' for d in b.depends_on)]
    If empty:
        if any blocked in current phase: ScheduleWakeup(1800, "blockers"); halt cycle
        if all current phase merged: phase-gate flow (step 12) and halt
6.  Sort ready by (phase, complexity_rank, id) ascending. brief = ready[0]
7.  git checkout -b feature/<brief.id>
    Edit frontmatter state=in_progress
    (pre-commit regenerates manifest)
    git commit -m "chore: claim {brief.id}"
    git push -u origin feature/<brief.id>
8.  Invoke /work-on-brief brief.id
9.  Outcome:
        success → state=review (auto-merge will fire); ScheduleWakeup(120, "CI running")
        needs-iteration → /handle-ci-failure (max 2 iterations)
        blocked → /enter-blocked-state; halt
10. CI green AND self-review comment → auto-merge fires
    GH workflow manifest-on-merge.yml updates frontmatter state=merged
11. ScheduleWakeup(60, "next brief")
12. Phase-gate flow on last brief merged in phase:
        scripts/phase_summary.py → docs/progress/phase{N}-summary.md
        Update docs/briefs/phase_pointer.yaml: phase_state = "awaiting_{N+1}_approval"
        Pre-commit hook regenerates manifest.yaml
        Commit + push
        GH workflow notify-phase-complete.yml → Telegram
        Halt
```

### 5.2 Sub-skills

**`/work-on-brief <brief-id>`** (`.claude/skills/work-on-brief.md`):
1. Read brief MD + linked ADR sections (from `touches_adrs`) + relevant design specs.
2. Plan: enumerate ACs, map each to test file + test name (per `## Test Coverage Required`).
3. For each AC in order:
   - Write failing test first (red).
   - Implement minimum code to pass (green).
   - Refactor if needed.
4. Run `import-linter`, `mypy --strict`, `ruff check + format`, coverage check.
5. Update `docs/api-contract.yaml` if API surface changed (via `scripts/generate_openapi.py`).
6. `git commit -m "feat(<context>): <title> [<brief-id>]"`.
7. `git push`.
8. `gh pr create --template` (template includes AC↔test mapping placeholder Claude fills).
9. Invoke `/self-review-pr`.
10. Return `success | needs-iteration | blocked`.

**`/self-review-pr`** (`.claude/skills/self-review-pr.md`):
1. Re-read Done Definition from brief.
2. For each item, verify in current PR.
3. If all ✓: `gh pr comment` "Done Definition checked, all ACs verified by named tests <list>, no architectural drift."
4. Otherwise: return `needs-iteration` with specific failing item.

**`/handle-ci-failure`** (`.claude/skills/handle-ci-failure.md`):
1. `gh run list --branch <branch> --limit 1` → run-id.
2. `gh run view <run-id> --log-failed` → CI logs.
3. Diagnose: lint / type / test / coverage / architectural.
4. Fix locally, run tests, push.
5. If second failure on same brief: invoke `/enter-blocked-state`.

**`/enter-blocked-state`** (`.claude/skills/enter-blocked-state.md`):
1. Write `phase{N}-briefs/blocked/<brief-id>.md` (canonical location for all BLOCKED notes — one file per blocked brief; survives commit history; `/unblock-brief` deletes it). Structured content: what was tried, what failed (CI log excerpt), what input is needed from the human.
2. Edit brief frontmatter `state=blocked`.
3. `git commit -m "chore: block <brief-id> [BLOCKED]"`.
4. `git push`.
5. GH workflow `notify-blocked.yml` triggers (path filter on `phase*-briefs/blocked/**`) → Telegram.
6. Halt.

**`/sync-architecture`** (`.claude/skills/sync-architecture.md`):
1. Read `docs/architecture-decisions.md` (full).
2. Read `docs/progress/phase{current}-log.md` last 3 lines.
3. Read `.claude/CLAUDE.md`.
4. Hold all in working memory for the cycle.

### 5.3 Slash commands (operator interface)

**`/approve-phase <N>`** (`.claude/commands/approve-phase.md`):
*Semantics: "approve transition INTO phase N." User runs `/approve-phase 2` after phase 1 finishes; this opens phase 2 work.*

1. Read `docs/briefs/phase_pointer.yaml`.
2. Validate `phase_state == "awaiting_{N}_approval"` and all phase N-1 briefs are `state=merged`.
3. Update `phase_pointer.yaml`: `current_phase: N`, `phase_state: in_progress`.
4. Pre-commit hook regenerates `manifest.yaml` accordingly.
5. `git commit -m "chore: approve phase N"`, `git push`.
6. If `/loop` is active, next tick picks up; otherwise user re-runs `/loop /autonomous-build`.

**`/unblock-brief <brief-id>`** (`.claude/commands/unblock-brief.md`):
1. Read frontmatter, verify `state=blocked`.
2. Edit frontmatter `state=ready`, delete `phase{N}-briefs/blocked/<brief-id>.md`.
3. Commit, push.
4. Loop picks up.

**`/status`** (`.claude/commands/status.md`):
Print snapshot:
```
Current phase: 2 (in_progress)
Briefs: 17 total · 14 merged · 1 in_progress · 1 review · 0 blocked · 1 ready
Last 5 progress log entries (truncated)
Active branch: feature/phase2-custody-002
Last CI status: green (run #234)
```

### 5.4 Telegram notifications

**`notify-blocked.yml`** triggers on push that touches `phase*-briefs/blocked/**` or commits with `[BLOCKED]` in message:
```
🚧 BLOCKED: phase2-custody-001
Reason: <first non-empty line of "What input is needed">
File: <github URL>/blob/main/phase2-briefs/blocked/phase2-custody-001.md
```

**`notify-phase-complete.yml`** triggers on push to `main` that changes `manifest.yaml` to set `phase_state` to `awaiting_*_approval`:
```
🎯 Phase 1 complete · 18/18 briefs merged
Summary: <github URL>/blob/main/docs/progress/phase1-summary.md
Time: 14d 3h (estimated 14d) · CI failures: 7 (avg 0.4 per brief)
Next: run `/approve-phase 2` in your claude session
```

### 5.5 `CLAUDE.md` (project memory)

Verbatim contract Claude Code reads at every cycle start. Includes:
- 6 invariants from ADR §intro
- Loop discipline (TDD, ADR conflict handling, max 2 CI iterations, conventional commits, branch naming)
- Forbidden actions (`git push --force`, `git commit --no-verify`, `pip install` outside Poetry, `# type: ignore` without justification, manual manifest edits, modifying tests to make them pass)
- Precedence rules: ADR § > claude-code-spec.md > claude-design-spec.md > notes (for technical contracts; design-spec wins for visual/UX)

## 6. CI/CD pipelines

### 6.1 `ci-backend.yml` (8-stage per ADR §5)

| Stage | Job | Depends on | Time budget |
|---|---|---|---|
| 1 | Lint: ruff, mypy strict, import-linter, frontmatter+manifest validation | — | <2min |
| 2 | Domain tests (hypothesis ci profile, 50 examples) | 1 | <30s |
| 3 | Application tests (fakes, no I/O) | 1 (parallel with 2) | <2min |
| 4 | Adapter tests (testcontainers + Anvil + solana-test-validator) | 1 | <5min |
| 5 | Contract tests (FastAPI TestClient, full local stack) | 2, 3, 4 | <8min |
| 6 | E2E tests (Playwright, 10–15 critical journeys) | 5 | 3–5min |
| 7 | Coverage gate (combine, per-directory thresholds via `scripts/check_coverage.py`) | 2, 3, 4, 5, 6 | <30s |
| 8 | OpenAPI/errors-reference drift checks | 5 | <30s |

Total CI time: ~15–20 minutes per PR.

### 6.2 `ci-frontend.yml`

```yaml
- pnpm install --frozen-lockfile
- pnpm --filter web run lint && pnpm --filter web run typecheck
- pnpm --filter @vaultchain/admin run lint && typecheck
- pnpm run build (both apps)
- pnpm --filter web run test (vitest unit)
- bundle size check (warn if web > 500KB gzipped)
```

### 6.3 `manifest-on-merge.yml`

```yaml
on:
  pull_request:
    types: [closed]
jobs:
  update-state:
    if: github.event.pull_request.merged == true
    permissions: { contents: write }
    steps:
      - extract brief_id from branch name "feature/<brief-id>"
      - python scripts/transition_brief_state.py "$BRIEF_ID" merged
      - python scripts/gen_manifest.py
      - append entry to docs/progress/phase{N}-log.md
      - git commit -m "chore: mark $BRIEF_ID merged [skip ci]"
      - git push
```

### 6.4 `deploy.yml`

```yaml
on:
  push:
    branches: [main]
needs: [ci-backend, ci-frontend]
jobs:
  - Build backend Docker (multi-stage, ~150MB final)
  - fly deploy --strategy bluegreen --app vaultchain-api
  - Wait /healthz returns 200 (max 2min)
  - Build web dist, push to Cloudflare Pages "vaultchain-app"
  - Build admin dist, push to Cloudflare Pages "vaultchain-admin"
  - Smoke test against api.<USER_DOMAIN>/healthz, /openapi.json
  - Telegram notify on success/failure
```

### 6.5 `notify-blocked.yml`, `notify-phase-complete.yml`, `openapi-drift.yml`

See §5.4 for content. `openapi-drift.yml` runs in CI Stage 8 and on PRs touching backend; verifies `docs/api-contract.yaml` matches FastAPI's generated OpenAPI; fails with "OpenAPI drift; regenerate via `python scripts/generate_openapi.py`".

## 7. Test infrastructure

### 7.1 `pyproject.toml` pytest config

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
  "slow: tests >1s",
  "live: tests against real external services (manual only)",
]
filterwarnings = ["error"]   # warnings fail tests

[tool.coverage.run]
source = ["src/vaultchain"]
branch = false

[tool.coverage.report]
fail_under = 85   # global

# scripts/check_coverage.py enforces per-directory thresholds:
#   vaultchain.shared.domain                              95%
#   vaultchain.{ledger,custody,transactions,chains}.domain 95%
#   vaultchain.*.domain                                   90%
#   vaultchain.*.application                              85%
```

### 7.2 Hypothesis profiles (`backend/conftest.py`)

```python
from hypothesis import settings, HealthCheck

settings.register_profile("dev", max_examples=10, deadline=None)
settings.register_profile("ci", max_examples=50, deadline=timedelta(seconds=10))
settings.register_profile("nightly", max_examples=500, suppress_health_check=[HealthCheck.too_slow])
settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "dev"))
```

### 7.3 `docker-compose-dev.yml`

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    ports: ["5432:5432"]
    environment: { POSTGRES_PASSWORD: dev, POSTGRES_DB: vaultchain }
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
  mailhog:
    image: mailhog/mailhog
    ports: ["1025:1025", "8025:8025"]      # SMTP + UI for local console-email testing
  localstack:
    image: localstack/localstack:lite
    environment: { SERVICES: kms }
    ports: ["4566:4566"]
  anvil:
    image: ghcr.io/foundry-rs/foundry
    ports: ["8545:8545"]
    command: anvil --chain-id 11155111 --block-time 2
  solana-validator:
    profiles: ["solana"]   # opt-in: docker compose --profile solana up
    image: solanalabs/solana:stable
    command: solana-test-validator --reset
    ports: ["8899:8899", "8900:8900"]
```

`make dev` boots compose + uvicorn (with reload) + vite dev for both SPAs in parallel.

### 7.4 `tests/conftest.py` (root) fixtures

Session-scoped fixtures:
- `postgres_engine` (testcontainers or external compose)
- `redis_client`
- `anvil_rpc` (Phase 2+)
- `solana_validator` (Phase 3+, lazy)
- `localstack_kms`
- `vcr_cassette_path` (Tron, Sumsub recordings; per-test scope)

Function-scoped:
- `clean_db` (truncate-before-each-test)
- Factory-boy + scenario builders per ADR §5.

## 8. Architectural enforcement

### 8.1 `pyproject.toml` import-linter contracts

```toml
[tool.importlinter]
root_package = "vaultchain"

[[tool.importlinter.contracts]]
name = "AI never imports Custody"
type = "forbidden"
source_modules = ["vaultchain.ai"]
forbidden_modules = ["vaultchain.custody"]

[[tool.importlinter.contracts]]
name = "Domain never imports infra"
type = "forbidden"
source_modules = [
  "vaultchain.identity.domain", "vaultchain.kyc.domain",
  "vaultchain.wallet.domain", "vaultchain.custody.domain",
  "vaultchain.chains.domain", "vaultchain.ledger.domain",
  "vaultchain.balances.domain", "vaultchain.transactions.domain",
  "vaultchain.contacts.domain", "vaultchain.notifications.domain",
  "vaultchain.pricing.domain", "vaultchain.ai.chat.domain",
  "vaultchain.ai.tools.domain", "vaultchain.ai.suggestions.domain",
  "vaultchain.ai.memory.domain"
]
forbidden_modules = ["vaultchain.*.infra"]

[[tool.importlinter.contracts]]
name = "Custody only sees ApprovedTx, not Transaction"
type = "forbidden"
source_modules = ["vaultchain.custody.application", "vaultchain.custody.domain"]
forbidden_modules = ["vaultchain.transactions.domain"]

[[tool.importlinter.contracts]]
name = "Cross-context write goes through gateways"
type = "forbidden"
source_modules = ["vaultchain.transactions.application"]
forbidden_modules = [
  "vaultchain.custody.infra", "vaultchain.chains.infra",
  "vaultchain.ledger.infra", "vaultchain.kyc.infra"
]
```

Phase 4 adds 2 more contracts (per `phase4-ai-001` + `phase4-ai-007`):
- "AI sub-domains do not import ai.infra"
- "ai.memory raw SQL banned in application"

### 8.2 `mypy --strict` on entire `backend/src/vaultchain`

Configuration in `pyproject.toml`:
```toml
[tool.mypy]
strict = true
python_version = "3.12"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
no_implicit_optional = true
plugins = ["pydantic.mypy"]
```

## 9. `BOOTSTRAP-RUNBOOK.md` (operator side)

The runbook lives at `vaultchain/BOOTSTRAP-RUNBOOK.md` and is the only manual touchpoint between scaffolding and `/loop` launch.

### Sections

1. **Provisioning checklist** (~30–60 min):
   - GitHub repo (private/public)
   - Fly.io: account, flyctl, `fly auth login`
   - Cloudflare: account, API token (Pages perms)
   - Neon: project, connection string (us-east-1)
   - Upstash: Redis instance, rediss:// URL
   - AWS: IAM user with KMS perms, creds
   - Sumsub sandbox: app token, secret, webhook secret
   - Anthropic API key (Phase 4)
   - Google AI Studio: Gemini API key (Phase 4)
   - Resend: account, verified sender domain (Phase 2)
   - Sentry: 2 projects (vaultchain-backend, vaultchain-frontend), DSNs
   - Telegram: bot via @BotFather, `TG_BOT_TOKEN`, `TG_CHAT_ID`
   - Domain (optional for V1; placeholder OK)

2. **GitHub secrets** (15 entries, set via `gh secret set`).

3. **Branch protection** (`gh api` PUT; require PR + status checks + dismiss stale + no force-push).

4. **Local environment** (Python 3.12 via pyenv, pnpm 9, Docker, gh + fly CLI).

5. **Repo bootstrap** (one-time):
   ```bash
   cd ~/projects/vaultchain
   git init && git add -A && git commit -m "chore: initial bootstrap [phase1-shared-001 phase1-shared-002]"
   git remote add origin git@github.com:<USER>/vaultchain.git
   git push -u origin main
   gh secret set FLY_API_TOKEN < ...     # full list per GitHub secrets section
   ```

6. **Local services smoke**:
   ```bash
   docker compose -f docker-compose-dev.yml up -d
   cd backend && poetry install && poetry run pytest    # 0 tests, exits 0
   pnpm install
   pnpm --filter web dev    # localhost:5173 → empty SPA
   ```

7. **Day-1 launch**:
   ```bash
   claude
   > /loop /autonomous-build
   # Claude works through phase1-shared-003 onward
   ```

8. **Maintenance playbook**: brief blocked → fix → `/unblock-brief`; phase done → review → `/approve-phase N`; CI flake recipes; stop/resume loop.

## 10. Day-1 launch sequence (resume)

```
1. I scaffold everything above (~15-30 min of tool calls).
2. I make initial git commit containing:
   - phase1-shared-001 satisfied (the bootstrap commit IS this brief)
   - phase1-shared-002 satisfied (FastAPI app factory + config)
   - 65 other briefs with frontmatter, state=ready
   - manifest.yaml generated
   - dependency-graph.mmd generated
3. User runs BOOTSTRAP-RUNBOOK §1-6 (provisioning + repo setup + secrets).
4. User runs `claude` + `/loop /autonomous-build`.
5. Loop runs to Phase 1 complete (~14 days estimate).
6. Telegram pings → user reviews summary → `/approve-phase 2`.
7. Continue through Phase 4 complete.
8. Demo recorded.
```

## 11. Estimate

- Repo skeleton: ~30 files (Dockerfile, pyproject, package.json, configs).
- Backend stub: app factory + config + 13 empty context dirs.
- Web/admin stubs: Vite + tokens.css imports + empty App.
- `.claude/` orchestration: 1 CLAUDE.md + 6 skills + 3 commands + 1 hook.
- Scripts: 6 Python utilities (~200–400 lines each).
- `.github/workflows/`: 7 workflows.
- 67 brief frontmatter retrofit.
- BOOTSTRAP-RUNBOOK.md.
- ADR-001..007 stubs.
- This spec doc.

**~80–100 files, 3000–5000 lines.**

## 12. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Claude Code drifts from brief content during impl | Wrong code merged | Done Definition + AC↔test mapping enforced in self-review; BLOCKED on import-linter break |
| CI fails repeatedly on flaky test | Loop stuck | Max 2 iterations → BLOCKED → human inspects |
| Phase-gate not triggered correctly | Loop runs into phase 2 prematurely | manifest.phase_state mutation requires last brief merged AND scripts/phase_summary.py run |
| User forgets to `/approve-phase` | Loop sleeps forever | Telegram nudge at phase complete; `/status` shows wait state |
| Auto-merge merges incomplete PR | Partial impl on main | Branch protection requires CI green; self-review comment is gating signal Claude provides only when checklist passes |
| Manifest hand-edited | Source-of-truth violation | CI `--check` mode rejects drift; merge blocked. `phase_pointer.yaml` is the ONLY hand-mutable input. |
| Branch protection requires review but Claude can't self-approve | PR stuck waiting on review | Branch protection set to require status checks only (no approval); self-review comment is Claude's discipline gate. Documented in §2 table. |
| ScheduleWakeup interval poorly tuned | Loop wastes tokens or misses signals | Codified intervals: 60s after merge (next brief), 120s when CI running, 1800s when blocked or awaiting phase approval, 60s when idle. Tunable via env vars in `autonomous-build` skill. |
| Frontmatter retrofit corrupts brief | Lose existing content | Retrofit done by Python script that ONLY adds frontmatter and removes `## Status` block; rest of file untouched; git diff reviewed |
| Loop runs over a long weekend, machine sleeps | Loop pauses | ScheduleWakeup timeout; on resume `claude` re-invoke |

## 13. Out of scope (deferred)

- IaC (Terraform/Pulumi) for Cloudflare/Fly/Neon/Upstash — V2; runbook handles V1 manually.
- Multi-developer collaboration (multiple humans + Claude) — V1 assumes single operator.
- Cloud-hosted Claude Code (GitHub Action runner) — V1 is local `/loop`; can switch later by adding a workflow.
- Advanced observability (per-brief cost dashboards, Prometheus, structured-log dashboards beyond Sentry) — V2.
- Per-brief retry policies beyond 2 iterations — by design, blocked is the answer; humans diagnose root cause.
- Auto-recovery from `blocked` state via Claude — humans must `/unblock-brief` after fix.

## 14. Success criteria

- [ ] User can `cd vaultchain && claude && /loop /autonomous-build` and walk away.
- [ ] Phase 1 completes without operator intervention beyond `/approve-phase` at end.
- [ ] Phase 2/3/4 same.
- [ ] All 67 briefs merged on `main`.
- [ ] Live deployment at `app.<USER_DOMAIN>`, `admin.<USER_DOMAIN>`, `api.<USER_DOMAIN>` (or Fly default URLs).
- [ ] Demo video recorded.
- [ ] Operator total intervention: ~30 min provisioning + ~15 min phase-gate reviews × 4 = ~90 min total.

## 15. Approval status

- [x] Bootstrap scope: A (all-on-host)
- [x] Runtime: A (local `/loop`)
- [x] Manifest strategy: 1 (frontmatter-first)
- [x] Section 1 design (repo skeleton + .claude/)
- [x] Section 2 design (frontmatter + manifest pipeline)
- [x] Section 3 design (autonomous-build skill + phase-gate)
- [x] Section 4 design (CI/CD + test infra + bootstrap runbook + day-1)
- [ ] Final spec review by user (gate before invoking writing-plans skill)

---

## Addendum (2026-04-27): Hosting model changed to Hetzner-minimum

**This supersedes** the multi-cloud SaaS hosting discussed in the original brainstorm (Fly.io + Cloudflare Pages + Neon + Upstash + AWS KMS). The architectural decisions (DDD, hexagonal, 13 contexts, money/ledger invariants, import-linter contracts) are UNCHANGED — only the deploy model.

See `docs/decisions/ADR-012-hosting-model.md` for the full rationale.

Key changes from the original spec:
- §2 brainstorm choices table: hosting row now reads "single Hetzner Cloud VM with docker-compose-prod"
- §6.4 deploy.yml: SSH + GHCR-pull instead of flyctl + wrangler
- §9 BOOTSTRAP-RUNBOOK §1-3: Hetzner provisioning instead of Fly/Cloudflare/Neon/Upstash
- New artifacts: `docker-compose-prod.yml`, `Caddyfile`, `scripts/deploy-server.sh`
- Removed artifact: `fly.toml`

The phase1-deploy-001 brief was rewritten to match. All other phase briefs are infra-agnostic.
