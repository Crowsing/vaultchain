# VaultChain Bootstrap Runbook

> Operator-side checklist. Complete sections 1-6 once before launching the autonomous build.

## 1. External service provisioning (~30-60 min)

Create accounts and capture credentials:

| Service | Purpose | What to capture |
|---|---|---|
| GitHub | Code host + Actions runner | Personal/org account; create empty repo `<USER>/vaultchain` |
| Fly.io | Backend host | `fly auth login`; capture `FLY_API_TOKEN` (`fly tokens create deploy --expiry 8760h`) |
| Cloudflare | Pages host (web + admin) | API token with Pages:Edit; `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` |
| Neon | Postgres (serverless, branching) | Project `vaultchain`; capture `DATABASE_URL` (postgresql+asyncpg variant) |
| Upstash | Redis (idempotency, sessions, rate-limit) | Database `vaultchain`; capture `REDIS_URL` (rediss://) |
| AWS | KMS for envelope encryption | IAM user with `kms:Encrypt`, `kms:Decrypt`, `kms:GenerateDataKey`; capture `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `KMS_KEY_ID` |
| Sumsub sandbox | KYC verification | App + secret + webhook secret; `SUMSUB_APP_TOKEN`, `SUMSUB_SECRET_KEY`, `SUMSUB_WEBHOOK_SECRET` |
| Anthropic | Claude API for AI features (phase 4) | `ANTHROPIC_API_KEY` |
| Google AI Studio | Gemini embeddings (phase 4) | `GOOGLE_AI_STUDIO_API_KEY` |
| Resend | Transactional email (phase 2+) | Verified sender domain; `RESEND_API_KEY` |
| Sentry | Error tracking | 2 projects (`vaultchain-backend`, `vaultchain-frontend`); capture both DSNs |
| Telegram | Phase-gate + blocked notifications | `@BotFather` → bot; capture `TG_BOT_TOKEN`; start chat with bot, query `https://api.telegram.org/bot<TOKEN>/getUpdates` to find `TG_CHAT_ID` |
| Domain | (optional V1) | Register or leave `<USER_DOMAIN>` literal until phase1-deploy-001 |

## 2. GitHub secrets

Run from repo root (or via the GitHub UI under Settings → Secrets):

```bash
gh secret set FLY_API_TOKEN --body "$FLY_API_TOKEN"
gh secret set CLOUDFLARE_API_TOKEN --body "$CF_TOKEN"
gh secret set CLOUDFLARE_ACCOUNT_ID --body "$CF_ACCOUNT"
gh secret set DATABASE_URL --body "$NEON_URL"
gh secret set REDIS_URL --body "$UPSTASH_URL"
gh secret set AWS_ACCESS_KEY_ID --body "$AWS_KEY"
gh secret set AWS_SECRET_ACCESS_KEY --body "$AWS_SECRET"
gh secret set AWS_REGION --body "us-east-1"
gh secret set KMS_KEY_ID --body "$KMS_KEY"
gh secret set SUMSUB_APP_TOKEN --body "$SUMSUB_APP"
gh secret set SUMSUB_SECRET_KEY --body "$SUMSUB_SECRET"
gh secret set SUMSUB_WEBHOOK_SECRET --body "$SUMSUB_WEBHOOK"
gh secret set ANTHROPIC_API_KEY --body "$ANTHROPIC_KEY"
gh secret set GOOGLE_AI_STUDIO_API_KEY --body "$GEMINI_KEY"
gh secret set RESEND_API_KEY --body "$RESEND_KEY"
gh secret set SENTRY_DSN_BACKEND --body "$SENTRY_DSN_BACK"
gh secret set SENTRY_DSN_FRONTEND --body "$SENTRY_DSN_FRONT"
gh secret set SECRET_KEY --body "$(openssl rand -hex 32)"
gh secret set TG_BOT_TOKEN --body "$TG_BOT_TOKEN"
gh secret set TG_CHAT_ID --body "$TG_CHAT_ID"
```

## 3. Branch protection on `main`

```bash
gh api -X PUT "repos/<USER>/vaultchain/branches/main/protection" \
  -F "required_status_checks[strict]=true" \
  -F "required_status_checks[contexts][]=Stage 1 — lint + frontmatter + manifest" \
  -F "required_status_checks[contexts][]=Stage 7 — coverage gate" \
  -F "required_status_checks[contexts][]=Stage 8 — OpenAPI/errors-reference drift" \
  -F "enforce_admins=false" \
  -F "required_pull_request_reviews=" \
  -F "restrictions=" \
  -F "allow_force_pushes=false" \
  -F "allow_deletions=false" \
  -F "required_linear_history=true" \
  -F "required_conversation_resolution=true"
```

**Important:** required_pull_request_reviews is intentionally empty — Claude cannot self-approve.
The merge gate is (a) green CI status checks AND (b) the `/self-review-pr` PR comment.

Enable auto-merge for PRs that meet status checks:

```bash
gh api --method PATCH "repos/<USER>/vaultchain" \
  -f allow_auto_merge=true \
  -f allow_squash_merge=true \
  -f allow_merge_commit=false \
  -f allow_rebase_merge=false \
  -f delete_branch_on_merge=true
```

## 4. Local environment

Required toolchain (operator-side):

```bash
# Python
pyenv install 3.12.7
pyenv local 3.12.7
pipx install poetry==1.8.4
pipx install pre-commit==4.0.1

# Node
nvm install 20.11.1
nvm use 20.11.1
npm install -g pnpm@9

# Docker (for compose dev stack)
# Install Docker Desktop or docker-ce per OS

# CLIs
brew install gh flyctl    # macOS
# or per-OS equivalents

gh auth login
fly auth login
```

## 5. Repo bootstrap (one-time)

```bash
cd ~/projects/vaultchain

# After Claude finishes scaffolding (Tasks 1-15 of the plan):
git remote add origin git@github.com:<USER>/vaultchain.git
git push -u origin main

# Verify GH workflows fire (the first push triggers ci-backend + ci-frontend):
gh run list --limit 3
gh run watch     # optional: live status
```

## 6. Local services smoke

```bash
# Bring up postgres + redis + mailhog + localstack + anvil
docker compose -f docker-compose-dev.yml up -d

# Backend health
cd backend
poetry install --with dev
poetry run pytest                          # 0-3 tests, exits 0
poetry run uvicorn vaultchain.main:app --port 8000 &
sleep 2
curl http://localhost:8000/healthz         # {"status":"ok"}
kill %1

# Frontend health
cd ..
pnpm install
pnpm --filter @vaultchain/web dev          # http://localhost:5173 → blank "VaultChain"
# Ctrl-C
pnpm --filter @vaultchain/admin dev        # http://localhost:5174 → blank "VaultChain Admin"
```

## 7. Day-1 launch — start the autonomous loop

```bash
cd ~/projects/vaultchain
claude

# Inside claude:
> /loop /autonomous-build
```

Claude will:
1. Read `.claude/CLAUDE.md` + `docs/architecture-decisions.md`
2. Pick the first ready brief in phase 1 (likely `phase1-shared-003`)
3. TDD-implement it, open PR, self-review, auto-merge
4. Repeat until phase 1 finishes
5. Set `phase_state: awaiting_2_approval`, push, halt
6. Telegram: 🎯 Phase 1 complete — Next: run `/approve-phase 2`

**Walk away.** Claude will work for ~14 days on phase 1.

## 8. Maintenance playbook

### Brief blocked

You'll receive: 🚧 BLOCKED: phaseN-context-NNN — Reason: <…>

1. Read `phaseN-briefs/blocked/<brief-id>.md`.
2. Address the input (commit a fix, amend an ADR, or supply credentials).
3. From your claude session: `/unblock-brief <brief-id>`.
4. Loop resumes on next tick.

### Phase complete

You'll receive: 🎯 Phase N complete — Next: run `/approve-phase <N+1>`

1. Read `docs/progress/phase{N}-summary.md` on GitHub.
2. (Optional) inspect the merged PRs and the deployed environment.
3. From your claude session: `/approve-phase <N+1>`.

### Stop and resume the loop

- Stop: Ctrl-C the `claude` session.
- Resume: `claude` then `/loop /autonomous-build` again.

### CI flake

If a single CI run fails on a known flaky test, the loop's `/handle-ci-failure` retries up to 2x. After that the brief is blocked. To force a re-run on a blocked brief without changing input:

```bash
gh run rerun <run-id>
# Then in claude:
/unblock-brief <brief-id>
```

### Forced halt

`docs/briefs/phase_pointer.yaml` → set `phase_state: complete` to halt permanently.

---

When the V1 demo is recorded, the loop has done its job.
