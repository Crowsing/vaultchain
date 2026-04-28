# Operational Runbook

> Phase 1 covers deploy verification + the day-1 levers (logs, seed
> admin, rollback). Later operational concerns (incident response
> playbooks, cost-overrun mitigation, manual KYC override) are filled
> by `phase4-ops-001`. For Day-1 bootstrap of a new VM, see
> `BOOTSTRAP-RUNBOOK.md`.

---

## Phase 1 deploy verification

Run after every successful `Deploy` workflow on `main`.

### 1 — Confirm the workflow finished green

- GitHub → Actions → `Deploy` workflow → latest run on `main`.
- All three jobs (`build-image`, `build-frontend`, `deploy`) should be
  green.
- The `deploy` job's last step posts a Telegram notification (`✅ Deploy
  success — <sha>`). If the chat didn't get it, check `TG_BOT_TOKEN` /
  `TG_CHAT_ID` GitHub Secrets.

### 2 — Confirm the live URLs respond

```bash
# Backend healthz (returns 200 + {"status":"ok","checks":{"database":"ok","redis":"ok"}})
curl -fsS "https://api.<USER_DOMAIN>/healthz" | jq .

# Public OpenAPI surface — must NOT contain any /admin/ paths
curl -fsS "https://api.<USER_DOMAIN>/openapi.json" \
  | jq '.paths | keys[] | select(startswith("/admin"))'
# expect: empty output

# User SPA root
curl -fsSI "https://app.<USER_DOMAIN>/" | head -1
# expect: HTTP/2 200

# Admin SPA root
curl -fsSI "https://admin.<USER_DOMAIN>/" | head -1
# expect: HTTP/2 200
```

### 3 — Seed an admin user (first deploy only)

```bash
ssh deploy@<HETZNER_HOST>
cd /opt/vaultchain
docker compose -f docker-compose-prod.yml exec -T api \
  python -m vaultchain.cli.scripts.seed_admin \
    --email "<your-admin@example.com>" \
    --password "<a strong password ≥12 chars>" \
    --full-name "Operator" \
    --role admin \
    --accept-secret-display
```

The CLI prints the TOTP otpauth URI and 10 backup codes ONCE — scan the
URI with Authy/1Password and store the backup codes in your password
manager **before pressing Enter**. There is no recovery path other than
re-running the CLI to seed a second admin.

### 4 — Walk the user signup flow

> Phase 1's email adapter is console-mode — magic-link tokens are
> visible in the api container logs. Phase 2 swaps in Resend.

1. Open `https://app.<USER_DOMAIN>/` in an **incognito window** (so
   cookies start clean and DNS is freshly resolved).
2. Sign up with a fresh email.
3. SSH in and grep the magic link:
   ```bash
   ssh deploy@<HETZNER_HOST> \
     "docker compose -f /opt/vaultchain/docker-compose-prod.yml \
        logs --tail=200 api" \
     | grep -E 'magic_link_token|magic-link'
   ```
4. Open the printed URL in the same incognito window → enter the TOTP
   secret in your authenticator → land on the dashboard.

### 5 — Walk the admin login flow

1. Open `https://admin.<USER_DOMAIN>/` in incognito.
2. Sign in with the email + password from step 3.
3. Enter the TOTP code → see the four zero-count queue cards on
   `/dashboard`.
4. Click "Sign out" → returns to `/login`.

### 6 — Confirm Sentry receives a test error

Trigger a deliberate failure end-to-end:

```bash
ssh deploy@<HETZNER_HOST> \
  "docker compose -f /opt/vaultchain/docker-compose-prod.yml exec -T api \
     python -c 'import sentry_sdk; sentry_sdk.capture_message(\"deploy verify\")'"
```

Sentry → `vaultchain-backend` project → Issues → expect a fresh "deploy
verify" message with the current `release: <sha>` tag.

### 7 — Attach screenshots to the deploy PR

For posterity (and to satisfy AC-phase1-deploy-001-11): take screenshots
of the dashboard, admin login, and Sentry message and paste them into
the deploy PR's description.

---

## Logs

```bash
# All services on the VM
ssh deploy@<HETZNER_HOST> \
  "docker compose -f /opt/vaultchain/docker-compose-prod.yml logs -f"

# Just the api
ssh deploy@<HETZNER_HOST> \
  "docker compose -f /opt/vaultchain/docker-compose-prod.yml logs -f api"

# Last 200 lines (no follow)
ssh deploy@<HETZNER_HOST> \
  "docker compose -f /opt/vaultchain/docker-compose-prod.yml logs --tail=200 api worker"
```

Sentry has structured exception traces with `request_id` correlation
once a real DSN is wired (Phase 1 backend init only — frontend SDK
follows in a later brief).

---

## Database migrations

Migrations run automatically in the deploy job (`scripts/deploy-server.sh`
runs `alembic upgrade head` BEFORE bringing services up). To run
manually after a hotfix:

```bash
ssh deploy@<HETZNER_HOST>
cd /opt/vaultchain
docker compose -f docker-compose-prod.yml run --rm api alembic upgrade head
docker compose -f docker-compose-prod.yml up -d  # (re-bring services up)
```

To inspect history:

```bash
docker compose -f docker-compose-prod.yml run --rm api alembic history
```

---

## Rollback

The deploy is image-based. To revert to the previous green deploy:

1. Find the previous `sha-<commit>` in GHCR:
   <https://github.com/<USER>/vaultchain/pkgs/container/vaultchain-api>
2. SSH in and pin the image:
   ```bash
   ssh deploy@<HETZNER_HOST>
   cd /opt/vaultchain
   export VAULTCHAIN_IMAGE="ghcr.io/<USER>/vaultchain-api:sha-<previous>"
   bash /opt/vaultchain/deploy-server.sh
   ```
3. Confirm `/healthz` is 200, run smoke flow.

> Database migrations are forward-only by convention. If a migration in
> the bad release was destructive (very rare in Phase 1), restore from
> the latest restic snapshot per `BOOTSTRAP-RUNBOOK.md` §6.5.

If the rollback is also bad, freeze deploys (`gh workflow disable
deploy.yml`) and dig in.

---

## Sections (later phases)

- Incident response (Sentry alert → Telegram → on-call)
- Secret rotation
- Manual KYC override
- Failed-broadcast recovery
- AI cost-overrun mitigation
