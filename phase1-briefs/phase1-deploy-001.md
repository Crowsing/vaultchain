---
id: phase1-deploy-001
phase: 1
context: deploy
title: Deploy backend Fly.io + frontends Cloudflare Pages
complexity: M
sdd_mode: lightweight
estimated_hours: 4
state: ready
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

# Brief: phase1-deploy-001 — Deploy backend to Fly.io + frontends to Cloudflare Pages


## Title

Deploy backend Fly.io + frontends Cloudflare Pages

## Context

Phase 1's product exit criterion is "deployed empty skeleton on live URL" (per `00-product-identity.md`). This brief realizes that: backend deployed to Fly.io as a single Docker image running both user (`/api/v1/...`) and admin (`/admin/api/v1/...`) routers in one ASGI process, plus the outbox publisher worker as a second Fly machine in the same app. User SPA deployed to Cloudflare Pages at `app.vaultchain.io`. Admin SPA deployed to Cloudflare Pages at `admin.vaultchain.io`. Postgres on Neon (free tier — Phase 1 needs only 1GB and burst CPU). Redis on Upstash (free tier — opaque token storage + idempotency cache). All infrastructure on free or trial tiers; total cost ~$0/month for the demo period, scaling to ~$25/month once a real custodial wallet runs in Phase 2.

The brief delivers: `Dockerfile` for backend, `fly.toml` (api + worker process groups), `_redirects` and `_headers` files for Cloudflare Pages, GitHub Actions workflows for deploy on push to `main` (lint, test, build, deploy), Sentry SDK initialization in backend + both SPAs (using DSNs from secrets), DNS configuration (Cloudflare DNS for `vaultchain.io` with `app`, `admin`, `api` records), and CORS setup so the frontends can talk to the API across subdomains while keeping cookie-domain logic intact.

The cookie-domain decision is the trickiest piece. The user app at `app.vaultchain.io` and admin at `admin.vaultchain.io` both need to send cookies to `api.vaultchain.io`. The chosen pattern: cookies are scoped to `Domain=.vaultchain.io` (parent domain, both subdomains can read), but with path restrictions — admin cookie path is `/admin/api/v1/`, user cookie path is `/api/v1/`. SameSite=Lax allows cross-subdomain navigation. CORS on the backend accepts `app.vaultchain.io` and `admin.vaultchain.io` with `credentials: true`. This works because the actual XHR is to `api.vaultchain.io` from both apps; the browser sends the right cookie based on path.

Domain is registered separately by the operator (Namecheap or similar). This brief assumes the domain `vaultchain.io` (or whatever the operator chose) is present and DNS is delegated to Cloudflare. If the operator has a different domain, the brief uses placeholders `<USER_DOMAIN>`, `<API_DOMAIN>`, `<ADMIN_DOMAIN>` that are filled at execution time.

---

## Architecture pointers

- **Layer:** infrastructure / ops (no domain layer involvement).
- **Packages touched:** `Dockerfile`, `fly.toml`, `apps/admin/_redirects`, `apps/admin/_headers`, `web/_redirects`, `web/_headers`, `.github/workflows/ci-backend.yml`, `.github/workflows/ci-frontend.yml`, `.github/workflows/deploy.yml`, `infra/cloudflare-dns.md` (a checklist, not Terraform — Phase 2 brief can introduce IaC if needed), `backend/src/observability/sentry.py`, `web/src/lib/sentry.ts`, `apps/admin/src/lib/sentry.ts`.
- **Reads / writes / events / migrations:** none (operational only). Migrations from prior Phase 1 briefs are run automatically on backend container boot via Alembic upgrade.
- **OpenAPI:** ensure `/docs`, `/redoc`, `/openapi.json` are served at `api.vaultchain.io/docs` etc. — public, admin-filtered.

---

## Acceptance Criteria

- **AC-phase1-deploy-001-01:** Given the backend repo at `main`, when GitHub Actions runs `deploy.yml`, then a Docker image is built (Python 3.12 slim, Poetry resolved deps, source baked in), pushed to Fly.io, and deployed as two process groups: `api` (uvicorn on $PORT serving the FastAPI app) and `worker` (the outbox publisher arq from shared-004). Both groups share the same DB pool config and Redis URL. Health check `/healthz` returns 200 within 30s of deploy.

- **AC-phase1-deploy-001-02:** Given Postgres provisioned on Neon (project `vaultchain-prod`, region `us-east-1` or closest to Fly region), when the backend container boots, then `alembic upgrade head` runs as a startup hook, applying all migrations from identity-001 + the outbox migration from shared-003. Idempotent: re-running the deploy is safe.

- **AC-phase1-deploy-001-03:** Given Redis provisioned on Upstash (TLS-enabled REST API + native protocol), when the backend uses Redis for opaque token storage and idempotency cache, then both work. The Upstash URL is in Fly secrets as `REDIS_URL` (rediss://...). `aioredis` is the client.

- **AC-phase1-deploy-001-04:** Given the user SPA repo at `web/`, when GitHub Actions runs `ci-frontend.yml` on push to `main`, then `pnpm --filter web build` runs and the `dist/` is published to Cloudflare Pages project `vaultchain-app`. The deployment is bound to the `app.vaultchain.io` custom domain. `_redirects` file routes all unknown paths to `/index.html` (SPA mode). `_headers` file sets `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, and a Content-Security-Policy that allows the API origin only.

- **AC-phase1-deploy-001-05:** Given the admin SPA repo at `apps/admin/`, when GitHub Actions runs `ci-frontend.yml` on push to `main`, then it builds and deploys to Cloudflare Pages project `vaultchain-admin`, bound to `admin.vaultchain.io`. Same `_redirects` and `_headers` patterns. CSP excludes anything not strictly needed.

- **AC-phase1-deploy-001-06:** Given the cookie-domain configuration, when the user app at `app.vaultchain.io` calls `api.vaultchain.io/api/v1/auth/me` after login, then the user access cookie `vc_at` (path `/api/v1/`) is sent and the request succeeds. When the admin app at `admin.vaultchain.io` calls `api.vaultchain.io/admin/api/v1/auth/me`, the admin access cookie `admin_at` (path `/admin/api/v1/`) is sent. CORS allows both origins with `credentials: true`. All session cookies are `Domain=.vaultchain.io`, `Secure`, `HttpOnly`. SameSite per identity-004 + admin-002: `vc_at`/`vc_csrf` use `SameSite=Lax`; `vc_rt` (path `/api/v1/auth/refresh`) and `admin_rt` (path `/admin/api/v1/auth/refresh`) use `SameSite=Strict`; `admin_at`/`admin_csrf` use `SameSite=Lax`.

- **AC-phase1-deploy-001-06b:** Given both SPAs are live on their respective subdomains, when an authed Playwright/curl call from each origin hits its corresponding `auth/me` endpoint with cookies attached (default browser behavior with `credentials: include` / `--cookie-jar`), then both succeed with 200; when a vc_* cookie is presented at an `/admin/api/v1/...` endpoint, the path-restricted cookie is NOT sent by the browser (and the request is rejected `401 identity.session_required`); when an admin_* cookie is presented at `/api/v1/...`, it is similarly not sent (verifies path isolation works in practice, not just in theory). This AC is verified manually via `docs/runbook.md` "Phase 1 deploy verification" — a curl matrix per environment is sufficient.

- **AC-phase1-deploy-001-07:** Given Sentry is provisioned (free tier, two projects: `vaultchain-backend` and `vaultchain-frontend`), when an error occurs in any of the three apps, then it is reported to Sentry with the `request_id` correlating across backend and frontend. The Sentry DSN is in env / GH secrets, never in repo. Source maps for both SPAs are uploaded as a CI step (`@sentry/cli`).

- **AC-phase1-deploy-001-08:** Given the Telegram notification setup from `architecture-decisions.md` Section 6, when a deploy fails OR a brief enters `blocked` state, then `notify-blocked.yml` (referenced in setup-prompt; ensured to exist or created here) sends a message to the configured chat ID. The `TG_BOT_TOKEN` and `TG_CHAT_ID` GH secrets are required and validated at the start of the workflow.

- **AC-phase1-deploy-001-09:** Given the deployed system, when an operator manually runs `python -m cli.scripts.seed_admin --email <e> --password <p>` against the production database (via `fly ssh console` into the api machine), then an admin user is created. The CLI is bundled in the backend Docker image. Deploy runbook (added to `docs/runbook.md`) documents this step.

- **AC-phase1-deploy-001-10:** Given the public OpenAPI surface at `api.vaultchain.io/docs`, when accessed without auth, then it renders the user-facing endpoints only — admin endpoints (`/admin/api/v1/...`) are filtered out per the configuration from admin-002. This is checked manually post-deploy and a smoke test in CI hits `/openapi.json` and asserts no path starts with `/admin/`.

- **AC-phase1-deploy-001-11:** Given the deployed apps, when an end-to-end smoke test runs against the live URLs (a small Playwright spec executed manually post-deploy, not blocking CI), then: signup → magic link (Phase 1 console adapter mode — magic-link tokens are surfaced via `fly logs --app vaultchain-api` and the runbook documents the operator's `fly logs | grep magic_link_token` recipe; Phase 2 swaps in a real email adapter and the smoke flips to inbox-based capture) → TOTP enroll → land on dashboard. This proves the deploy is actually live, not just CI-green. The smoke spec is in `tests/e2e/phase1_deploy_smoke.spec.ts` and is gated behind `PLAYWRIGHT_LIVE=1` so it never runs in CI by accident.

---

## Out of Scope

- IaC (Terraform / Pulumi) for Cloudflare / Fly / Neon / Upstash: V2 — Phase 1 uses checklists.
- Custom domain TLS certificates: handled automatically by Fly + Cloudflare.
- CDN / WAF rules beyond Cloudflare's defaults: V2.
- Backup automation for Postgres (Neon has built-in 7-day point-in-time): V2.
- Multi-region deploy: not budgeted; single region is correct for V1 testnet portfolio.
- Real production-grade SMTP (SES / Postmark): the email port stays in console-adapter mode in Phase 1; magic links are surfaceable from logs. Phase 2 adds a real adapter.
- Status page (Statuspage / Atlassian): V2.
- Performance monitoring beyond Sentry breadcrumbs: V2.

---

## Dependencies

- **Code dependencies:** all Phase 1 backend + frontend briefs merged.
- **Data dependencies:** all Phase 1 migrations applied successfully in CI before deploy.
- **External dependencies (operator-provisioned, secrets in GH + Fly):** Cloudflare account + DNS delegation, Fly.io account + `flyctl auth`, Neon account + connection string, Upstash account + Redis URL, Sentry account + DSNs, Telegram bot token + chat ID, domain registered. The operator does these manually (no automation in V1).

---

## Test Coverage Required

- [ ] **CI smoke check:** post-deploy step in `deploy.yml` curls `https://api.vaultchain.io/healthz` and asserts 200; curls `https://api.vaultchain.io/openapi.json` and asserts no path starts with `/admin/`.
- [ ] **Manual checklist:** a `docs/runbook.md` section "Phase 1 deploy verification" listing the manual steps to run post-deploy (seed admin, hit /signup from a real browser, complete the magic-link + TOTP flow against the live URL, screenshot the dashboard, screenshot the admin login).

> Lightweight mode. No backend tests added in this brief; the work is operational.

---

## Done Definition

- [ ] All ACs verified, with manual checklist outcomes attached to the PR (screenshots of live URLs, Sentry receiving an error, Telegram receiving a deploy notification).
- [ ] `Dockerfile` builds locally without warnings.
- [ ] `fly.toml` is committed; `fly deploy` from a clean checkout works (operator-tested).
- [ ] CI workflows pass on a no-op commit pushed to `main`.
- [ ] No secrets in repo; everything in GH Secrets + Fly secrets.
- [ ] ADR-005 drafted (deploy topology) — even if short, it justifies the Fly+Cloudflare+Neon+Upstash choice for a portfolio reviewer who wonders "why this stack."
- [ ] `docs/runbook.md` created with: deploy steps, seed-admin step, rollback procedure (revert + redeploy), how to check logs (Fly logs + Sentry).
- [ ] Single PR. Conventional commit: `chore(infra): deploy backend to Fly.io + frontends to Cloudflare Pages [phase1-deploy-001]`.

---

## Implementation Notes

- The Dockerfile uses a multi-stage build: stage 1 installs Poetry deps into a venv, stage 2 copies the venv + source into a slim Python image. Final image ~150MB.
- Fly process groups: `api = "uvicorn backend.main:app --host 0.0.0.0 --port $PORT --workers 2"`, `worker = "python -m backend.workers.outbox_publisher"`. Both use the same image; `fly.toml` declares `[processes]` block.
- Health check: a tiny `/healthz` endpoint that returns `{ok: true}` plus DB ping (`SELECT 1`) plus Redis ping. Sentry-sampled at 1% to keep free tier healthy.
- CORS: use `fastapi.middleware.cors.CORSMiddleware` with `allow_origins=[USER_ORIGIN, ADMIN_ORIGIN]`, `allow_credentials=True`, `allow_methods=["GET","POST","PATCH","DELETE","OPTIONS"]`, `allow_headers=["Content-Type","X-Idempotency-Key","X-CSRF-Token"]`.
- Cloudflare Pages `_redirects` for SPA mode: `/* /index.html 200`. `_headers`: per-route security headers, with the most restrictive CSP that still allows the API origin and Sentry's ingest endpoint.
- Sentry: in backend, `sentry_sdk.init(dsn=..., traces_sample_rate=0.05, environment="production", release=GIT_SHA)`. In frontend, the React/Vite SDK with same config + sourcemap upload.
- Telegram notification GH Action: a single step that posts to `https://api.telegram.org/bot<TG_BOT_TOKEN>/sendMessage` with a markdown-formatted body referencing the run URL and brief ID.
- Run Alembic on container start, but only on the `api` process — guard with an env var `RUN_MIGRATIONS=1` set in the api process group only, so the worker doesn't race.

---

## Risk / Friction

- DNS propagation can take up to an hour even with Cloudflare. Time the deploy step to avoid surprise. The CI smoke check should retry with backoff on the live-URL curls — first 5 minutes after a cold deploy can flap.
- The cookie-domain logic is correct on paper but easy to get wrong in practice (one missing flag = cross-site cookie blocked by Chrome). Test the full flow in an incognito window with a fresh DNS resolution after deploy. Document the verification steps in the runbook precisely.
- Fly free tier has cold-start latency of ~3s on first request after idle. For portfolio-demo purposes this is fine; document it. If a reviewer hits the URL after hours of idle, the first signup is slow.
- The console email adapter means magic-link tokens are visible in Fly logs. Anyone with `fly logs` access can hijack signups. Acceptable for testnet portfolio; explicit warning in ADR-005 about not promoting to a real product without swapping the adapter.
- Sentry free tier: 5K errors/month. If the deployed app has a noisy bug, the budget burns quickly. Sample errors aggressively (`traces_sample_rate=0.05`). The SDK config makes this easy.
- `notify-blocked.yml` referenced in setup-prompt may or may not yet exist. This brief is responsible for making it exist by Phase 1 close.
