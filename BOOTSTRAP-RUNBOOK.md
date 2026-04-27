# VaultChain Bootstrap Runbook

> Operator-side checklist. Complete sections 1-6.5 once before launching the autonomous build.
> **Hosting model:** single Hetzner Cloud VM with `docker-compose-prod.yml` (see `docs/decisions/ADR-012-hosting-model.md`).

## 1. External service provisioning (~30-60 min)

Create accounts and capture credentials:

| Service | Purpose | What to capture |
|---|---|---|
| GitHub | Code host + Actions runner + GHCR for backend image | Personal/org account; create empty repo `<USER>/vaultchain`. GHCR is automatic via `GITHUB_TOKEN` (`packages: write` permission in `deploy.yml`). |
| Hetzner Cloud | Single VM running everything | Account; create 1 VM (CPX21 recommended: 3 vCPU, 4GB RAM, 80GB SSD, ~5.5€/mo) running Ubuntu 24.04 LTS or Debian 12. Locally generate an SSH key (`ssh-keygen -t ed25519 -f ~/.ssh/vaultchain_deploy_ed25519`). Add the public key to the VM via Hetzner Console. Capture the VM IPv4. (Optional: capture a Hetzner API token if you want to use `hcloud` CLI.) |
| Hetzner Storage Box | Off-VM backup target for restic | BX11 ~3.5€/mo for 1TB. Capture SFTP credentials (user `u<id>`, host `u<id>.your-storagebox.de`). |
| Cloudflare | DNS only (free tier) | Add domain; set NS records at registrar. Create A records `app`, `admin`, `api` → VM IPv4. **Disable the Cloudflare proxy (orange cloud → grey cloud) for `api.<USER_DOMAIN>`** so Caddy can issue Let's Encrypt directly via HTTP-01. Optional: leave proxy on for `app`/`admin` once Caddy has issued certs (or grey-cloud all three for simplicity). |
| Sumsub sandbox | KYC verification | App + secret + webhook secret; `SUMSUB_APP_TOKEN`, `SUMSUB_SECRET_KEY`, `SUMSUB_WEBHOOK_SECRET` |
| Anthropic | Claude API for AI features (phase 4) | `ANTHROPIC_API_KEY` |
| Google AI Studio | Gemini embeddings (phase 4) | `GOOGLE_AI_STUDIO_API_KEY` |
| Resend | Transactional email (phase 2+) | Verified sender domain; `RESEND_API_KEY` |
| Sentry | Error tracking (free tier) | 2 projects (`vaultchain-backend`, `vaultchain-frontend`); capture both DSNs |
| Telegram | Phase-gate + blocked + deploy notifications | `@BotFather` → bot; capture `TG_BOT_TOKEN`; start chat with bot, query `https://api.telegram.org/bot<TOKEN>/getUpdates` to find `TG_CHAT_ID` |
| Domain | (required for V1 deploy) | Register; delegate NS to Cloudflare per the Cloudflare row above. |

## 2. GitHub secrets

Run from repo root (or via the GitHub UI under Settings → Secrets):

```bash
gh secret set HETZNER_HOST --body "<vm-ipv4-or-fqdn>"
gh secret set HETZNER_SSH_KEY --body "$(cat ~/.ssh/vaultchain_deploy_ed25519)"   # PRIVATE key
gh secret set USER_DOMAIN --body "<your-domain.tld>"
gh secret set ACME_EMAIL --body "<your-email>"

gh secret set SUMSUB_APP_TOKEN --body "$SUMSUB_APP"
gh secret set SUMSUB_SECRET_KEY --body "$SUMSUB_SECRET"
gh secret set SUMSUB_WEBHOOK_SECRET --body "$SUMSUB_WEBHOOK"
gh secret set ANTHROPIC_API_KEY --body "$ANTHROPIC_KEY"
gh secret set GOOGLE_AI_STUDIO_API_KEY --body "$GEMINI_KEY"
gh secret set RESEND_API_KEY --body "$RESEND_KEY"
gh secret set SENTRY_DSN_BACKEND --body "$SENTRY_DSN_BACK"
gh secret set SENTRY_DSN_FRONTEND --body "$SENTRY_DSN_FRONT"

gh secret set SECRET_KEY --body "$(openssl rand -hex 32)"
gh secret set MASTER_KEY --body "$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
gh secret set POSTGRES_PASSWORD --body "$(openssl rand -hex 24)"

gh secret set TG_BOT_TOKEN --body "$TG_BOT_TOKEN"
gh secret set TG_CHAT_ID --body "$TG_CHAT_ID"
```

> Image hosting uses GHCR (the built-in `${{ secrets.GITHUB_TOKEN }}`); no extra registry credential is needed.

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
brew install gh           # macOS (or per-OS equivalent)
gh auth login

# Optional: restic for testing backup procedures locally
brew install restic       # macOS, or `apt install restic`
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

## 6.5. Server-side bootstrap — one-time on the VM

```bash
# SSH to the VM as root or sudo-capable user
ssh root@<vm-ipv4>

# Install Docker + git + helpers
apt update && apt install -y docker.io docker-compose-plugin git rsync restic

# Create deploy user (key-based ssh only)
adduser --disabled-password deploy
mkdir -p /home/deploy/.ssh
cp /root/.ssh/authorized_keys /home/deploy/.ssh/
chown -R deploy:deploy /home/deploy/.ssh
usermod -aG docker deploy

# Create app directory and secret files
mkdir -p /opt/vaultchain/{web-dist,admin-dist}
mkdir -p /etc/vaultchain/secrets
chown -R deploy:deploy /opt/vaultchain
chmod 700 /etc/vaultchain/secrets

# Write secrets (one file per secret — values from your password manager / GH secrets)
echo "$POSTGRES_PASSWORD" > /etc/vaultchain/secrets/postgres_password
echo "$SECRET_KEY"        > /etc/vaultchain/secrets/secret_key
echo "$MASTER_KEY"        > /etc/vaultchain/secrets/master_key
echo "$SUMSUB_APP"        > /etc/vaultchain/secrets/sumsub_app_token
echo "$SUMSUB_SECRET"     > /etc/vaultchain/secrets/sumsub_secret_key
echo "$SUMSUB_WEBHOOK"    > /etc/vaultchain/secrets/sumsub_webhook_secret
echo "$ANTHROPIC_KEY"     > /etc/vaultchain/secrets/anthropic_api_key
echo "$GEMINI_KEY"        > /etc/vaultchain/secrets/google_ai_studio_api_key
echo "$RESEND_KEY"        > /etc/vaultchain/secrets/resend_api_key
echo "$TG_BOT_TOKEN"      > /etc/vaultchain/secrets/telegram_bot_token
chmod 600 /etc/vaultchain/secrets/*

# Write env file (for non-secret config)
cat > /etc/vaultchain/env <<EOF
USER_DOMAIN=your-domain.tld
ACME_EMAIL=your-email
TELEGRAM_CHAT_ID=$TG_CHAT_ID
SENTRY_DSN_BACKEND=$SENTRY_DSN_BACK
EOF
chmod 644 /etc/vaultchain/env

# Configure firewall (Hetzner UI recommended; alternative: ufw)
# Allow: 22, 80, 443. Deny everything else inbound.

# Configure restic backup cron (nightly at 02:00)
cat > /etc/cron.d/vaultchain-backup <<EOF
0 2 * * * deploy bash -c 'cd /opt/vaultchain && docker compose -f docker-compose-prod.yml exec -T postgres pg_dumpall -U vaultchain | restic -r sftp:u<storagebox-id>@u<storagebox-id>.your-storagebox.de:/vaultchain backup --stdin --stdin-filename pg_dumpall.sql >> /var/log/vaultchain-backup.log 2>&1'
EOF

# Done. The next push to main will deploy.
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

### Inspect production logs / run a one-off command on the VM

```bash
ssh deploy@<vm-ipv4>
cd /opt/vaultchain
docker compose -f docker-compose-prod.yml logs -f api          # tail backend
docker compose -f docker-compose-prod.yml logs -f worker       # tail outbox worker
docker compose -f docker-compose-prod.yml exec api alembic current   # check migration state
docker compose -f docker-compose-prod.yml exec api python -m cli.scripts.seed_admin --email a@b --password 'pw'
```

### Forced halt

`docs/briefs/phase_pointer.yaml` → set `phase_state: complete` to halt permanently.

---

When the V1 demo is recorded, the loop has done its job.
