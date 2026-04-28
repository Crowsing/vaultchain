---
ac_count: 1
blocks:
- phase1-web-003
- phase1-web-004
- phase1-web-005
complexity: S
context: web
depends_on:
- phase1-web-001
- phase1-identity-005
estimated_hours: 4
id: phase1-web-002
phase: 1
sdd_mode: lightweight
state: in_progress
title: API client, TanStack Query setup, error boundary
touches_adrs: []
---

# Brief phase1-web-002: API client, TanStack Query setup, error boundary


## Context

Identity-005 published `docs/api-contract.yaml`. This brief generates TS types from it into `shared-types/src/index.ts`, builds an `apiFetch` wrapper that handles cookies (credentials: include), CSRF header injection (read from `csrf` cookie), idempotency-key generation (UUIDv4 stored in IndexedDB until terminal response), error envelope parsing, and TanStack Query client configuration. Plus a top-level error boundary that handles unrecognized error codes via "Something went wrong" + Sentry capture stub.

This is the plumbing every authenticated screen will use. Subsequent screen briefs only write hooks and components; they don't touch fetch directly.

---

## Architecture pointers

- **Layer(s):** `lib/` (fetch wrapper, query client), `components/` (error boundary)
- **Affected packages:** `web/src/lib/`, `shared-types/src/`
- **Reads from:** `docs/api-contract.yaml` (build-time), backend at runtime
- **Writes to:** `shared-types/src/index.ts` (generated, committed)
- **Publishes events:** `none`
- **Subscribes to events:** `none`
- **New ports introduced:** N/A (frontend)
- **New adapters introduced:** N/A
- **DB migrations required:** `no`
- **OpenAPI surface change:** `no`

---

## Acceptance Criteria

- **AC-phase1-web-002-01:** Given `pnpm --filter shared-types build`, when run, then `shared-types/src/index.ts` is generated from `docs/api-contract.yaml` via `openapi-typescript` and exports types like `paths["/api/v1/me"]["get"]["responses"][200]["content"]["application/json"]`.
- **AC-phase1-web-002-02:** Given the `apiFetch(path, options)` wrapper, when called with a relative path, then it issues a fetch with `credentials: "include"`, base URL from `import.meta.env.VITE_API_BASE_URL` (default `http://localhost:8000`), `Accept: application/json` header, and on mutating verbs additionally sets `X-CSRF-Token` (read from `csrf` cookie) and `Idempotency-Key` (UUIDv4 generated and persisted in IndexedDB under `idempotency:{path}:{requestKey}` until terminal response).
- **AC-phase1-web-002-03:** Given a backend response with the standard error envelope `{error: {code, message, details, request_id}}`, when received, then the wrapper throws an `ApiError` instance carrying the parsed `code`, `message`, `details`, `requestId`. Components catch by `code` (never by string match on `message`).
- **AC-phase1-web-002-04:** Given an unrecognized error code (not in the known-codes registry), when caught at the top-level error boundary, then a generic "Something went wrong" UI renders with the `request_id` shown to the user (so they can paste into support), and a Sentry capture stub is invoked (`captureException(error, { tags: { request_id, code } })` — Sentry SDK not actually wired in V1; the stub is a no-op function in `web/src/lib/sentry.ts` with a `// TODO(deploy): wire Sentry SDK` comment).
- **AC-phase1-web-002-05:** Given an idempotency-key already stored in IndexedDB for `(method, path, body-hash)`, when a retry is issued, then the same key is reused. On a successful 2xx response, the key is evicted. On a 4xx terminal error, the key is also evicted (no further retries by the user expected).
- **AC-phase1-web-002-06:** Given the TanStack Query client config, when set up, then `defaultOptions.queries.retry` is `(failureCount, error) => failureCount < 2 && !(error instanceof ApiError && error.status >= 400 && error.status < 500)` — retry on network/5xx, don't retry on 4xx; `staleTime` default 30s; query keys are typed.
- **AC-phase1-web-002-07:** Given the `<ErrorBoundary>` component wrapping the app, when a render error occurs, then a fallback UI shows the generic "Something went wrong" with a "Reload" button. Functional — no Sentry tie-in beyond the stub.

---

## Out of Scope

- SSE handling for `/api/v1/events`: Phase 3 brief (when transactions stream).
- Optimistic updates: Phase 3 (when first cancellable mutation arrives — `useCancelDraft`).
- Real Sentry SDK: deploy brief.
- i18n of error messages: V2.
- Offline-first / service worker: out of V1.

---

## Dependencies

- **Code dependencies:** `phase1-web-001`, `phase1-identity-005` (the OpenAPI source of truth).
- **Data dependencies:** none (frontend).
- **External dependencies:** `@tanstack/react-query`, `openapi-typescript`, `idb-keyval` for the IndexedDB layer.

---

## Test Coverage Required

- [ ] **Vitest unit tests:** `web/tests/unit/api-fetch.test.ts`, `web/tests/unit/error-boundary.test.tsx`
  - covers AC-02, -03, -04, -05, -07
  - test cases: `apifetch_includes_credentials_and_csrf`, `apifetch_generates_and_persists_idempotency_key`, `apifetch_reuses_key_on_retry`, `apifetch_evicts_key_on_terminal_response`, `apifetch_parses_error_envelope_into_apierror`, `error_boundary_renders_fallback_on_render_error`
- E2E does not apply at this brief.

---

## Done Definition

- [ ] All ACs verified by named test cases or manual smoke documented in PR.
- [ ] `pnpm --filter web tsc --noEmit` passes (using generated `shared-types`).
- [ ] `pnpm --filter web lint` passes.
- [ ] `shared-types/src/index.ts` is generated and committed; CI verifies fresh-generation matches commit.
- [ ] No hardcoded URLs — all paths come from generated types or env vars.
- [ ] No new ADR.
- [ ] Single PR. Conventional commit: `feat(web): API client + TanStack Query + error boundary [phase1-web-002]`.

---

## Implementation Notes

- `apiFetch` returns typed responses by accepting a path-and-method generic that indexes `paths` from `shared-types`. Pattern:
  ```
  const data = await apiFetch<"/api/v1/me", "get">("/api/v1/me");
  // data is typed as paths["/api/v1/me"]["get"]["responses"][200]["content"]["application/json"]
  ```
  Wrap in a small helper to avoid boilerplate.
- Idempotency-key is generated *inside* the wrapper, not by the caller. The caller passes `{ idempotent: true }` (default for POST/PATCH/DELETE/PUT, false for GET). The wrapper hashes `(method, path, body)` to produce the IndexedDB lookup key; if a record exists with the same hash and is unresolved, reuse. If it exists and is resolved, generate a new key (the caller is making a logically new request).
- `ApiError` carries `status: number, code: string, message: string, details: unknown, requestId: string`. Subclassing `Error`, `instanceof` works.
- Known error codes registry: a const map `KNOWN_CODES = {"identity.unauthenticated": "Please sign in", ...}`. The error boundary uses this to decide between "render specific" vs "render generic." The full list grows per phase as briefs add codes; keep this registry in `web/src/lib/error-codes.ts` and update it in each brief that introduces frontend-visible codes.
- TanStack Query DevTools are enabled in dev only via `import.meta.env.DEV`.

---

## Risk / Friction

- IndexedDB in jsdom (test env) needs `fake-indexeddb` polyfill. Set up via `vitest.setup.ts`.
- CORS in dev: backend on `:8000`, frontend on `:5173`, cookies require either same-origin or `credentials: include` + backend `allow_credentials=True` + explicit allowed origin (not wildcard). Document the local-dev config in `web/README.md`. Production uses same-origin via reverse proxy at the deploy brief.
- The `Idempotency-Key` is set by the *frontend* but the backend's idempotency middleware (`phase1-shared-006`) treats it as opaque. The frontend's reuse-on-retry semantics are correct as long as the backend treats the same key + same body as the same request. Bodies are JSON-serialized stably (sorted keys via a small util).
