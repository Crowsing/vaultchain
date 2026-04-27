# VaultChain

Custodial multi-chain wallet (Ethereum Sepolia, Tron Shasta, Solana Devnet) with Sumsub KYC and a Claude AI assistant.

## Architecture

- **Hexagonal**: 5 layers per bounded context (delivery, application, domain, infra, composition root).
- **13 contexts**: identity, kyc, wallet, custody, chains, ledger, balances, transactions, contacts, ai, notifications, pricing, admin.
- **Custody invariant**: AI never imports Custody (enforced by import-linter).
- **Money**: `NUMERIC(78,0)` / `Decimal` only — never float.
- **Real double-entry ledger** + outbox pattern + opaque session tokens (NOT JWT).

See `docs/architecture-decisions.md` for the full ADR (single source of truth).

## Project structure

- `backend/` — Python 3.12 + FastAPI + SQLAlchemy 2 async + Alembic
- `web/` — User SPA (Vite + React 19 + TS 5)
- `apps/admin/` — Admin SPA (Vite + React 19 + TS 5)
- `shared-types/` — OpenAPI-generated TS types
- `phase{1-4}-briefs/` — Implementation briefs (frontmatter-driven)
- `docs/briefs/manifest.yaml` — Auto-generated state of all briefs
- `.claude/` — Autonomous build orchestration

## Launching the autonomous build

See `BOOTSTRAP-RUNBOOK.md` for one-time provisioning. After that:

```bash
cd ~/projects/vaultchain
claude
> /loop /autonomous-build
```

Claude works through phase 1 briefs unattended, sleeps at phase boundaries, and pings Telegram when it needs `/approve-phase N` from you.

## Specs

- `docs/architecture-decisions.md` — Architecture decisions (binding)
- `specs/00-product-identity.md` — Product scope
- `specs/claude-code-spec.md` — Engineering spec (data model, API)
- `specs/claude-design-spec.md` — Visual design spec
- `specs/01-auth-onboarding.md` … `06-withdrawal-approval.md` — UX flows
- `docs/superpowers/specs/2026-04-27-sdd-infrastructure-design.md` — This bootstrap design

## License

MIT — see `LICENSE`.
