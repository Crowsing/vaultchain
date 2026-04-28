---
id: phase1-deploy-001
phase: 1
context: deploy
title: Deploy backend + frontends to single Hetzner VM via docker-compose-prod
complexity: M
sdd_mode: lightweight
estimated_hours: 4
state: merged
depends_on:
- phase1-identity-005
- phase1-web-003
- phase1-web-004
- phase1-web-005
- phase1-admin-003
blocks: []
touches_adrs: []
ac_count: 1
---

# Brief: phase1-deploy-001 — Deploy backend + frontends to single Hetzner VM via docker-compose-prod


## Title

Deploy backend + frontends to single Hetzner VM via docker-compose-prod

## Context

Phase 1's product exit criterion is "deployed empty skeleton on live URL" (per `00-product-identity.md`). This brief realizes that on the **Hetzner-minimum** hosting model adopted on 2026-04-27 (see `docs/decisions/ADR-012-hosting-model.md`):

- Backend FastAPI image is built in CI and pushed to **GHCR** (`ghcr.io/<USER>/vaultchain-api`).
- A single **Hetzner Cloud VM** runs `docker-compose-prod.yml` containing: Postgres 16+pgvector, Redis 7, the backend image as `api` + `worker` services, and Caddy 2 as the TLS-terminating reverse proxy.
- User SPA and admin SPA are pre-built `dist/` directories rsync'd to the VM and served by Caddy as static files at `app.<USER_DOMAIN>` and `admin.<USER_DOMAIN>`.
- Caddy automatically provisions Let's Encrypt certificates for all three subdomains. Cloudflare DNS (free tier, DNS-only — no proxy) points the records to the VM IPv4.
- Total cost: ~10-15€/mo (CPX21 + Storage Box) + AI tokens, with no per-service SaaS rentals beyond Sumsub / Anthropic / Resend / Sentry / Telegram.

The brief delivers: `Dockerfile` for the backend (already present, hosting-agnostic), `docker-compose-prod.yml` (already present, this brief verifies it), `Caddyfile` (already present), `scripts/deploy-server.sh` (already present), GitHub Actions workflows for build + deploy on push to `main` (lint, test, build image, build SPAs, rsync + ssh deploy), Sentry SDK initialization in backend + both SPAs (using DSNs from env on the VM and from secrets in CI for SPA builds), and CORS setup so the frontends can talk to the API across subdomains while keeping cookie-domain logic intact.

The cookie-domain decision is the trickiest piece. The user app at `app.<USER_DOMAIN>` and admin at `admin.<USER_DOMAIN>` both need to send cookies to `api.<USER_DOMAIN>`. The chosen pattern: cookies are scoped to `Domain=.<USER_DOMAIN>` (parent domain, both subdomains can read), but with path restrictions — admin cookie path is `/admin/api/v1/`, user cookie path is `/api/v1/`. SameSite=Lax allows cross-subdomain navigation. CORS on the backend accepts `app.<USER_DOMAIN>` and `admin.<USER_DOMAIN>` with `credentials: true`. This works because the actual XHR is to `api.<USER_DOMAIN>` from both apps; the browser sends the right cookie based on path.

Domain is registered separately by the operator (Namecheap or similar). This brief assumes the domain is present and DNS is delegated to Cloudflare (DNS-only, no proxy on `api.<USER_DOMAIN>` so Caddy can issue Let's Encrypt directly via HTTP-01). If the operator has a different domain, the brief uses placeholders `<USER_DOMAIN>`, `<API_DOMAIN>`, `<ADMIN_DOMAIN>` that are filled at execution time.

---

## Architecture pointers

- **Layer:** infrastructure / ops (no domain layer involvement).
- **Packages touched:** `Dockerfile`, `docker-compose-prod.yml`, `Caddyfile`, `scripts/deploy-server.sh`, `.github/workflows/ci-backend.yml`, `.github/workflows/ci-frontend.yml`, `.github/workflows/deploy.yml`, `backend/src/observability/sentry.py`, `web/src/lib/sentry.ts`, `apps/admin/src/lib/sentry.ts`. (`fly.toml` was removed in the Hetzner retrofit; it is not part of this brief's surface.)
- **Reads / writes / events / migrations:** none (operational only). Migrations from prior Phase 1 briefs are run by the deploy script as a one-shot `docker compose run --rm api alembic upgrade head` BEFORE bringing services up — this keeps migration runs explicit and out of the api container's startup hook so the worker doesn't race.
- **OpenAPI:** ensure `/docs`, `/redoc`, `/openapi.json` are served at `api.<USER_DOMAIN>/docs` etc. — public, admin-filtered.

---

## Acceptance Criteria

- **AC-phase1-deploy-001-01:** Given the backend repo at `main`, when GitHub Actions runs `deploy.yml`, then a Docker image is built (Python 3.12 slim, Poetry resolved deps, source baked in), pushed to GHCR (`ghcr.io/<USER>/vaultchain-api:sha-<sha>` and `:latest`), and the deploy job SSHes to the Hetzner VM where `docker-compose-prod.yml` brings up two services from the same image: `api` (uvicorn on port 8000 serving the FastAPI app) and `worker` (the outbox publisher arq from shared-004). Both services share the same DB pool config and Redis URL. Health check `/healthz` (proxied through Caddy at `https://api.<USER_DOMAIN>/healthz`) returns 200 within 60s of the SSH deploy step finishing.

- **AC-phase1-deploy-001-02:** Given Postgres provisioned in `docker-compose-prod.yml` (image `pgvector/pgvector:pg16`, named volume `postgres-data`, password loaded via Docker secret from `/etc/vaultchain/secrets/postgres_password`), when `scripts/deploy-server.sh` runs on the VM, then it executes `docker compose -f docker-compose-prod.yml run --rm api alembic upgrade head` BEFORE the `up -d` step, applying all migrations from identity-001 + the outbox migration from shared-003. Idempotent: re-running the deploy is safe.

- **AC-phase1-deploy-001-03:** Given Redis provisioned in `docker-compose-prod.yml` (image `redis:7-alpine`, AOF persistence with `--appendonly yes --save 60 1000`, named volume `redis-data`), when the backend uses Redis for opaque token storage and idempotency cache, then both work. The Redis URL is `redis://redis:6379/0` (in-network, plaintext is acceptable; the VM private network is the trust boundary).

- **AC-phase1-deploy-001-04:** Given the user SPA repo at `web/`, when GitHub Actions runs `deploy.yml` on push to `main`, then the `build-frontend` job runs `pnpm --filter @vaultchain/web build`, the resulting `web/dist/` is uploaded as an artifact, and the `deploy` job rsyncs it to the VM at `/opt/vaultchain/web-dist/`. Caddy serves it at `app.<USER_DOMAIN>` with `try_files {path} /index.html` for SPA routing and the security headers (Strict-Transport-Security, X-Content-Type-Options: nosniff, Referrer-Policy: strict-origin-when-cross-origin, Permissions-Policy, and a Content-Security-Policy that allows the API origin + Sumsub iframe only).

- **AC-phase1-deploy-001-05:** Given the admin SPA repo at `apps/admin/`, when GitHub Actions runs `deploy.yml` on push to `main`, then it builds and the `dist/` is rsync'd to `/opt/vaultchain/admin-dist/`. Caddy serves it at `admin.<USER_DOMAIN>` with the same security-header pattern but a stricter CSP (no Sumsub frame allowance — admin doesn't need it).

- **AC-phase1-deploy-001-06:** Given the cookie-domain configuration, when the user app at `app.<USER_DOMAIN>` calls `api.<USER_DOMAIN>/api/v1/auth/me` after login, then the user access cookie `vc_at` (path `/api/v1/`) is sent and the request succeeds. When the admin app at `admin.<USER_DOMAIN>` calls `api.<USER_DOMAIN>/admin/api/v1/auth/me`, the admin access cookie `admin_at` (path `/admin/api/v1/`) is sent. CORS allows both origins with `credentials: true`. All session cookies are `Domain=.<USER_DOMAIN>`, `Secure`, `HttpOnly`. SameSite per identity-004 + admin-002: `vc_at`/`vc_csrf` use `SameSite=Lax`; `vc_rt` (path `/api/v1/auth/refresh`) and `admin_rt` (path `/admin/api/v1/auth/refresh`) use `SameSite=Strict`; `admin_at`/`admin_csrf` use `SameSite=Lax`.

- **AC-phase1-deploy-001-06b:** Given both SPAs are live on their respective subdomains, when an authed Playwright/curl call from each origin hits its corresponding `auth/me` endpoint with cookies attached (default browser behavior with `credentials: include` / `--cookie-jar`), then both succeed with 200; when a vc_* cookie is presented at an `/admin/api/v1/...` endpoint, the path-restricted cookie is NOT sent by the browser (and the request is rejected `401 identity.session_required`); when an admin_* cookie is presented at `/api/v1/...`, it is similarly not sent (verifies path isolation works in practice, not just in theory). This AC is verified manually via `docs/runbook.md` "Phase 1 deploy verification" — a curl matrix per environment is sufficient.

- **AC-phase1-deploy-001-07:** Given Sentry is provisioned (free tier, two projects: `vaultchain-backend` and `vaultchain-frontend`), when an error occurs in any of the three apps, then it is reported to Sentry with the `request_id` correlating across backend and frontend. The backend Sentry DSN is in `/etc/vaultchain/env` on the VM (read by the api+worker containers via `SENTRY_DSN_BACKEND`); the frontend DSN is baked into the SPA bundle at build time via a CI build-arg from `secrets.SENTRY_DSN_FRONTEND`. Source maps for both SPAs are uploaded as a CI step (`@sentry/cli`).

- **AC-phase1-deploy-001-08:** Given the Telegram notification setup from `architecture-decisions.md` Section 6, when a deploy fails OR a brief enters `blocked` state, then `notify-blocked.yml` (referenced in setup-prompt; ensured to exist or created here) sends a message to the configured chat ID. Additionally, `deploy.yml` itself sends a Telegram message on success or failure of the deploy job. The `TG_BOT_TOKEN` and `TG_CHAT_ID` GH secrets are required and validated at the start of the workflow.

- **AC-phase1-deploy-001-09:** Given the deployed system, when an operator manually runs `docker compose -f docker-compose-prod.yml exec api python -m cli.scripts.seed_admin --email <e> --password <p>` over SSH on the VM, then an admin user is created. The CLI is bundled in the backend Docker image. Deploy runbook (added to `docs/runbook.md`) documents this step.

- **AC-phase1-deploy-001-10:** Given the public OpenAPI surface at `api.<USER_DOMAIN>/docs`, when accessed without auth, then it renders the user-facing endpoints only — admin endpoints (`/admin/api/v1/...`) are filtered out per the configuration from admin-002. This is checked manually post-deploy and a smoke test in CI hits `/openapi.json` (via the Caddy-proxied URL after the SSH deploy) and asserts no path starts with `/admin/`.

- **AC-phase1-deploy-001-11:** Given the deployed apps, when an end-to-end smoke test runs against the live URLs (a small Playwright spec executed manually post-deploy, not blocking CI), then: signup → magic link (Phase 1 console adapter mode — magic-link tokens are surfaced via `docker compose -f docker-compose-prod.yml logs api` over SSH and the runbook documents the operator's `docker compose logs api | grep magic_link_token` recipe; Phase 2 swaps in a real email adapter and the smoke flips to inbox-based capture) → TOTP enroll → land on dashboard. This proves the deploy is actually live, not just CI-green. The smoke spec is in `tests/e2e/phase1_deploy_smoke.spec.ts` and is gated behind `PLAYWRIGHT_LIVE=1` so it never runs in CI by accident.

---

## Out of Scope

- IaC (Terraform / Ansible) for Hetzner provisioning: V2 — V1 uses the runbook checklist (`BOOTSTRAP-RUNBOOK.md` §1, §6.5).
- Custom domain TLS certificates: handled automatically by Caddy via Let's Encrypt HTTP-01.
- CDN / WAF rules: V2. Cloudflare DNS is on free tier, DNS-only.
- Backup automation beyond the restic-to-Storage-Box cron documented in the runbook: V2.
- Multi-region / multi-VM deploy: not budgeted; single VM is correct for V1 testnet portfolio.
- Real production-grade SMTP (SES / Postmark): the email port stays in console-adapter mode in Phase 1; magic links are surfaceable from `docker compose logs`. Phase 2 adds a real adapter via Resend.
- Status page (Statuspage / Atlassian): V2.
- Performance monitoring beyond Sentry breadcrumbs: V2.

---

## Dependencies

- **Code dependencies:** all Phase 1 backend + frontend briefs merged.
- **Data dependencies:** all Phase 1 migrations applied successfully via `alembic upgrade head` in the deploy script before the first request hits the api service.
- **External dependencies (operator-provisioned, secrets in GH + on-VM secret files):** Hetzner Cloud VM + SSH key, Hetzner Storage Box (for restic backup), Cloudflare DNS (free tier — DNS only, no proxy on `api`), GitHub repo + GHCR access (`packages: write` on `GITHUB_TOKEN`), Sumsub sandbox, Anthropic + Google AI Studio + Resend keys, Sentry DSNs, Telegram bot token + chat ID, domain registered. The operator does these manually (no automation in V1) — `BOOTSTRAP-RUNBOOK.md` §1, §2, §6.5 walks through it.

---

## Test Coverage Required

- [ ] **CI smoke check:** post-deploy step in `deploy.yml` curls `https://api.<USER_DOMAIN>/healthz` with a 24× retry loop (5s sleep) and asserts 200; another curl hits `https://api.<USER_DOMAIN>/openapi.json` and asserts no path starts with `/admin/`.
- [ ] **Manual checklist:** a `docs/runbook.md` section "Phase 1 deploy verification" listing the manual steps to run post-deploy (seed admin via `docker compose exec`, hit /signup from a real browser, complete the magic-link + TOTP flow against the live URL, screenshot the dashboard, screenshot the admin login).

> Lightweight mode. No backend tests added in this brief; the work is operational.

---

## Done Definition

- [ ] All ACs verified, with manual checklist outcomes attached to the PR (screenshots of live URLs, Sentry receiving an error, Telegram receiving a deploy notification).
- [ ] `Dockerfile` builds locally without warnings.
- [ ] `docker-compose-prod.yml` is committed; `docker compose -f docker-compose-prod.yml config --quiet` exits 0; the stack boots cleanly on the VM (operator-tested).
- [ ] `Caddyfile` is committed; `caddy validate --config Caddyfile` exits 0 (with the relevant env vars set).
- [ ] CI workflows pass on a no-op commit pushed to `main`.
- [ ] No secrets in repo; everything in GH Secrets + on-VM `/etc/vaultchain/secrets/*` files.
- [ ] ADR-012 (hosting model) is in `docs/decisions/` and referenced from this brief.
- [ ] `docs/runbook.md` created with: deploy steps, seed-admin step, rollback procedure (revert + redeploy), how to check logs (`docker compose logs` + Sentry).
- [ ] Single PR. Conventional commit: `chore(infra): deploy backend + frontends to Hetzner VM via docker-compose-prod [phase1-deploy-001]`.

---

## Implementation Notes

- The Dockerfile uses a multi-stage build: stage 1 installs Poetry deps into a venv, stage 2 copies the venv + source into a slim Python image. Final image ~150MB. Hosting-agnostic — same image runs locally, in CI, and on the VM.
- `docker-compose-prod.yml` declares `api` and `worker` services from the same `${VAULTCHAIN_IMAGE}` reference; the `worker` overrides `command: ["arq", "vaultchain.shared.worker.WorkerSettings"]`. Both depend on the postgres+redis healthchecks.
- Health check: a tiny `/healthz` endpoint that returns `{ok: true}` plus DB ping (`SELECT 1`) plus Redis ping. Sentry-sampled at 1% to keep free tier healthy. The Compose-level healthcheck on the api service curls `http://localhost:8000/healthz` every 30s; Caddy's `depends_on: api: { condition: service_healthy }` waits on it.
- CORS: use `fastapi.middleware.cors.CORSMiddleware` with `allow_origins=[USER_ORIGIN, ADMIN_ORIGIN]`, `allow_credentials=True`, `allow_methods=["GET","POST","PATCH","DELETE","OPTIONS"]`, `allow_headers=["Content-Type","X-Idempotency-Key","X-CSRF-Token"]`. The CORS_ORIGINS env var in `docker-compose-prod.yml` is templated as `https://app.${USER_DOMAIN},https://admin.${USER_DOMAIN}`.
- Caddy SPA hosting: `try_files {path} /index.html` rewrites unmatched paths to the SPA entrypoint. Static assets are served with zstd/gzip compression. Per-host `header { ... }` blocks attach the security headers and CSP on every response.
- Sentry: in backend, `sentry_sdk.init(dsn=settings.sentry_dsn_backend, traces_sample_rate=0.05, environment="production", release=GIT_SHA)`. In frontend, the React/Vite SDK with same config + sourcemap upload.
- Telegram notification GH Action: a single step that posts to `https://api.telegram.org/bot<TG_BOT_TOKEN>/sendMessage` with a markdown-formatted body referencing the run URL and brief ID. `deploy.yml` includes a Telegram step `if: always()`.
- Migrations: run via `docker compose run --rm api alembic upgrade head` BEFORE `up -d` in `scripts/deploy-server.sh`. This avoids the worker racing the api on a startup-hook approach and keeps migration failures visible in the deploy step output.
- KMS replacement: `MASTER_KEY_PATH=/run/secrets/master_key` is mounted into both api and worker containers via Docker secrets. Phase 2 KMS brief implements envelope encryption with `cryptography.Fernet` keyed off the file's contents. The legacy AWS env vars (`aws_access_key_id`, `aws_secret_access_key`, `kms_key_id`) remain in `config.py` as optional placeholders for a future migration.

---

## Risk / Friction

- DNS propagation can take up to an hour even with Cloudflare DNS. Time the deploy step to avoid surprise. The CI smoke check retries with backoff on the live-URL curls — first 5 minutes after a cold deploy can flap.
- Caddy needs DNS to resolve the three subdomains to the VM IPv4 BEFORE it can issue Let's Encrypt certs. If `api.<USER_DOMAIN>` is behind the orange Cloudflare proxy, HTTP-01 challenge fails. **Grey-cloud at minimum the `api` record** (the runbook says so explicitly). DNS-01 is an option for later if proxy is desired.
- The cookie-domain logic is correct on paper but easy to get wrong in practice (one missing flag = cross-site cookie blocked by Chrome). Test the full flow in an incognito window with a fresh DNS resolution after deploy. Document the verification steps in the runbook precisely.
- Single-VM SPOF: a 30-min restic-restore RTO is the V1 mitigation. ADR-012 documents the trade-off.
- The console email adapter means magic-link tokens are visible in `docker compose logs api`. Anyone with SSH access to the VM (the `deploy` user) can hijack signups. Acceptable for testnet portfolio; explicit warning in ADR-012 about not promoting to a real product without swapping the adapter.
- Sentry free tier: 5K errors/month. If the deployed app has a noisy bug, the budget burns quickly. Sample errors aggressively (`traces_sample_rate=0.05`). The SDK config makes this easy.
- `notify-blocked.yml` referenced in setup-prompt may or may not yet exist. This brief is responsible for making it exist by Phase 1 close.
- File-based KMS at `/etc/vaultchain/secrets/master_key` is a single point of compromise: anyone with `root` on the VM can decrypt all custodial keys. ADR-012 accepts this for V1; phase 4+ migrates to AWS KMS without changing the envelope-encryption interface.
