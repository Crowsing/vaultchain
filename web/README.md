# @vaultchain/web

The user-facing single-page application.

## Local development

The frontend runs on `:5173`, the backend on `:8000`. Vite proxies `/api/*`
to `http://localhost:8000` (see `vite.config.ts`), so the dev server is
effectively same-origin.

If you need to call the backend from a different origin (e.g. running
the frontend at `http://localhost:5173` against a backend reachable via
LAN), the backend must:

- set `allow_credentials=True`
- whitelist the explicit origin (no wildcard)

Both are required because cookies (session + CSRF) are `httpOnly` /
`Secure` and only ride along when `credentials: "include"` is paired
with an explicit allowed origin on the server side.

The browser test setup (jsdom) includes `fake-indexeddb/auto` because
the idempotency-key store reads from IndexedDB.

## Generated types

`@vaultchain/shared-types` is regenerated from `docs/api-contract.yaml`
via:

```bash
pnpm --filter @vaultchain/shared-types build
```

CI verifies the committed `shared-types/src/index.ts` matches a fresh
codegen — see `scripts/check_shared_types_fresh.mjs`.

## Idempotency / CSRF / cookies

`apiFetch` (`src/lib/api-fetch.ts`) is the only place HTTP calls
should originate. It handles:

- `credentials: "include"` (sends the session cookie back)
- `X-CSRF-Token` from the `csrf` cookie on mutating verbs
- `Idempotency-Key` (UUIDv4, persisted in IndexedDB until terminal
  response) on mutating verbs

Errors come back as `ApiError` instances; components must catch by
`error.code`, never by string-matching `error.message`.
