---
ac_count: 1
blocks:
- phase1-identity-005
- phase1-admin-002
- phase1-shared-006
complexity: S
context: shared
depends_on: []
estimated_hours: 4
id: phase1-shared-005
phase: 1
sdd_mode: strict
state: ready
title: Error envelope mapper + DomainError → HTTP exception_handler
touches_adrs: []
---

# Brief phase1-shared-005: Error envelope mapper + DomainError → HTTP exception_handler


## Context

Architecture-decisions Section 4 fixes the error envelope: `{error: {code, message, details, request_id, documentation_url}}`. Every endpoint returns this shape on every error class. This brief delivers the FastAPI `exception_handler` registry, the `DomainError → HTTP status` mapping rules, and the `errors-reference.md` generator that scans the `DomainError` registry on CI and renders one section per code.

This brief intentionally introduces zero error codes — the `DomainError` base and four placeholder subclasses (`ValidationError`, `NotFoundError`, `ConflictError`, `PermissionError`) come from bootstrap. Concrete error subclasses arrive in their owning context briefs (e.g., `identity.errors.MagicLinkExpired` in `phase1-identity-002`).

This is the seam every later brief writes into. Get it wrong here and every endpoint inherits the bug.

---

## Architecture pointers

- **Layer(s):** `delivery` (FastAPI handlers), `infra` (errors-reference generator script)
- **Affected packages:** `vaultchain.shared.delivery`, `backend/scripts/generate_errors_reference.py`
- **Reads from:** `vaultchain.shared.domain.errors` (the `DomainError` class hierarchy)
- **Writes to:** `docs/errors-reference.md` (generator only — at CI/build time, not runtime)
- **Publishes events:** `none`
- **Subscribes to events:** `none`
- **New ports introduced:** `none`
- **New adapters introduced:** `none`
- **DB migrations required:** `no`
- **OpenAPI surface change:** `yes` — every endpoint's error response schema is updated to match the envelope; the `ErrorEnvelope` schema is added to OpenAPI components and referenced from every `4xx`/`5xx` response.

---

## Acceptance Criteria

- **AC-phase1-shared-005-01:** Given a FastAPI app with the handlers registered, when any endpoint raises a `DomainError` subclass, then the response body conforms to `{error: {code, message, details, request_id, documentation_url}}` and the HTTP status maps per the rules in architecture-decisions Section 4 (validation→400, auth→401, permission/tier→403, not found→404, conflict→409, semantic-validation→422, rate-limit→429, unexpected→500).
- **AC-phase1-shared-005-02:** Given an endpoint that raises `ValidationError`, when the response is built, then status is 400 and `error.code == "validation.<subcode>"` (the subcode comes from the subclass — placeholder allows `validation.invalid_input` for the generic case).
- **AC-phase1-shared-005-03:** Given an endpoint that raises `ConflictError` with `details={"current_version": 3, "expected_version": 2}`, when the response is built, then status is 409 and `details` round-trips to the body unchanged.
- **AC-phase1-shared-005-04:** Given any error response, when inspected, then `request_id` matches the `X-Request-ID` request header (generated upstream by middleware if absent) and is also present in the same request's structlog output.
- **AC-phase1-shared-005-05:** Given any error response, when inspected, then `documentation_url` is `https://docs.vaultchain.example/errors/{code}` (literal — no live page required at this brief).
- **AC-phase1-shared-005-06:** Given a Pydantic `RequestValidationError` (FastAPI's built-in, raised on schema mismatch), when caught by the handler, then the response uses the same envelope with `code="validation.request_schema"` and `details.fields` listing the failing fields with messages — i.e., FastAPI's default error shape is overridden, not coexisting.
- **AC-phase1-shared-005-07:** Given an unhandled `Exception` (not a `DomainError`), when caught, then the response is 500 with `code="internal.unexpected"`, `message` is a generic English string (no stack traces, no internal details exposed to the user), and the full exception is logged via Sentry/structlog with the `request_id`.
- **AC-phase1-shared-005-08:** Given the `DomainError` registry contains N subclasses, when `python scripts/generate_errors_reference.py` runs, then `docs/errors-reference.md` contains exactly N H2 sections, one per code, with fields {Code, HTTP status, Meaning, When emitted, Suggested user action, Related details fields}; the script is idempotent (running twice produces no diff).

---

## Out of Scope

- The `errors-reference.md` content is generated, not hand-edited — but the human-readable Meaning / Suggested user action come from class docstrings on each `DomainError` subclass. Adding those docstrings is the responsibility of the brief that introduces the subclass; this brief generates the page from whatever docstrings exist.
- I18n of `message`: out of V1. Frontend has its own i18n-aware mapping per architecture-decisions Section 4. `message` stays English here.
- Per-error rate limit: `code="rate_limit.exceeded"` mapping to 429 with `Retry-After` header is a Phase 2 concern (rate limit middleware proper) — this brief only adds the status mapping; the middleware lives in a later brief.
- Sentry SDK wiring: out of scope here, structlog only. Sentry integration arrives at the deploy brief (`phase1-deploy-001`) when production env is real.

---

## Dependencies

- **Code dependencies:** `vaultchain.shared.domain.errors` (bootstrap-delivered). FastAPI app factory in `vaultchain/main.py` (bootstrap-delivered as a stub).
- **Data dependencies:** `none`.
- **External dependencies:** `none`.

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/shared/domain/test_domain_error_subclassing.py`
  - covers AC-phase1-shared-005-02, -03 (the class hierarchy)
  - test cases: `test_validation_error_has_status_400`, `test_conflict_error_round_trip_details`, `test_code_format_dotted_lowercase`
- [ ] **Application tests:** `tests/shared/application/test_request_id_propagation.py`
  - covers AC-phase1-shared-005-04 (middleware-handler interaction with fake request)
  - test cases: `test_request_id_from_header_passes_through`, `test_request_id_generated_when_missing`
- [ ] **Contract tests:** `tests/api/test_error_envelope.py`
  - FastAPI TestClient with one fake endpoint per error type (test fixture endpoints, removed via override after suite)
  - covers AC-phase1-shared-005-01, -02, -03, -05, -06, -07
  - test cases: `test_validation_error_returns_400_envelope`, `test_conflict_error_returns_409_envelope`, `test_unexpected_exception_returns_500_generic_envelope`, `test_pydantic_validation_uses_envelope`, `test_documentation_url_format`
- [ ] **Adapter tests:** `tests/shared/infra/test_errors_reference_generator.py`
  - covers AC-phase1-shared-005-08
  - test cases: `test_generator_produces_one_section_per_subclass`, `test_generator_is_idempotent`, `test_generator_uses_class_docstring_for_meaning`

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All listed test categories implemented and passing locally.
- [ ] `import-linter` contracts pass.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Coverage ≥85% on `shared/delivery/`.
- [ ] OpenAPI schema updated: `ErrorEnvelope` component referenced from a default `responses` block on the app's `default_response_class`. Verify the diff in PR.
- [ ] No new ADR.
- [ ] Generator script runs in CI as part of stage 8 (OpenAPI/errors-reference drift check) per architecture-decisions Section 5; if `docs/errors-reference.md` changes from generation, CI fails until committed.
- [ ] Single PR. Conventional commit: `feat(shared): error envelope mapper + DomainError → HTTP handler [phase1-shared-005]`.
- [ ] PR description AC↔test map, ADRs (none).

---

## Implementation Notes

- Register handlers via `app.add_exception_handler(DomainError, domain_error_handler)` and `app.add_exception_handler(RequestValidationError, validation_handler)`. Order matters — register `DomainError` last to catch subclasses correctly.
- `request_id` generation lives in a thin middleware: read `X-Request-ID` header if present, else `f"req_{uuid7()}"`; bind via `structlog.contextvars.bind_contextvars`. Other briefs read it via the same contextvar.
- `code` format: `{context}.{condition}` dotted, lowercase, snake_case. Enforce via a regex in the `DomainError.__init_subclass__` so misformed codes fail at import time, not in production.
- Don't expose stack traces, ORM strings, or input echo on 500. The generic message is "Something went wrong on our end. Reference {request_id} when contacting support." Sentry capture is wired at deploy.
- The generator script reads classes via `pkgutil.walk_packages` then `inspect.getmembers(... predicate=lambda x: issubclass(x, DomainError))`. Skip the base class itself.

---

## Risk / Friction

- The `code` regex enforcement on `__init_subclass__` is the kind of bullet-proofing that makes test failures cryptic if a brief author types `code = "validationInvalid"` (camelCase). Make the assertion message helpful: include the offending class and the regex.
- `documentation_url` points to a domain that doesn't exist. That's intentional — the page is the generated `errors-reference.md` rendered via mkdocs-material per `pyproject.toml`. The deploy brief or a Phase 4 polish brief should host the docs page; track this as a non-blocking debt in `READY.md` (already mentioned).
