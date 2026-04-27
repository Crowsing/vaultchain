# ADR-012 — Hosting Model: Hetzner-minimum

**Status:** accepted (2026-04-27)
**Supersedes:** initial bootstrap design assumption (Fly.io + Cloudflare Pages + Neon + Upstash + AWS KMS)

## Decision

VaultChain V1 production runs on a **single Hetzner Cloud VM** with `docker-compose-prod.yml`:

- Postgres 16 + pgvector (Docker volume, restic backup to Hetzner Storage Box)
- Redis 7 (Docker, AOF)
- Backend image (FastAPI) from GHCR, runs as `api` + `worker` services
- Web + admin SPAs as pre-built `dist/` served by Caddy
- Caddy 2 as reverse proxy with automatic Let's Encrypt TLS

## Off-VM SaaS retained

Sumsub (KYC), Anthropic + Google AI Studio (AI), Resend (email), Sentry free tier, Telegram bot, Cloudflare DNS (free, DNS only).

## KMS replacement

`cryptography.Fernet` master key at `/etc/vaultchain/secrets/master_key` mounted as Docker secret. Phase 2 KMS brief implements envelope encryption with this primitive instead of AWS KMS. The `aws_*` env vars in `config.py` remain as optional placeholders for a future migration if scale requires it.

## Why

User-driven decision: minimize external service rentals to reduce monthly cost (~10-15€/mo on Hetzner + storage vs ~50-100€/mo with the multi-cloud setup) and surface area of credentials we manage.

## Trade-offs accepted

- No managed DB failover (single VM is the SPOF). Acceptable for V1; restic backups give RTO of ~30 min.
- No CDN for SPA assets (Caddy serves directly). Acceptable: assets are small (~200 KB gzipped); Cloudflare DNS proxy can be enabled later if perf demands.
- KMS is file-based, not HSM-backed. Acceptable for V1 testnet wallet with custodial keys behind a master key. Phase 4+ can migrate to AWS KMS without changing the envelope-encryption interface (config.py keeps the AWS env var placeholders).
- Deploy is SSH-based, not platform-managed. Acceptable: 1 server, predictable cadence.

## Implications for briefs

- `phase1-deploy-001` rewritten to target Hetzner + docker-compose-prod (this retrofit).
- Phase 2 KMS brief uses file-based master key, not boto3.
- `phase4-ops-*` briefs adjusted to reference `docker compose logs` and `docker compose exec` instead of `fly logs` / `fly ssh console`.
