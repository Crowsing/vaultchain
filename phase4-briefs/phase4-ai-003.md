---
ac_count: 12
blocks:
- phase4-ai-004
- phase4-ai-005
- phase4-ai-006
complexity: M
context: ai
depends_on:
- phase2-balances-001
- phase2-transactions-002
- phase3-kyc-001
estimated_hours: 4
id: phase4-ai-003
phase: 4
sdd_mode: strict
state: ready
title: Read-only tool catalog (`get_balances`, `get_recent_transactions`, `get_kyc_status`)
touches_adrs: []
---

# Brief: phase4-ai-003 — Read-only tool catalog (`get_balances`, `get_recent_transactions`, `get_kyc_status`)


## Context

This brief delivers the **catalog half** of the AI tools sub-system: the `Tool` Protocol, the `ToolCatalog` aggregator, the `ToolResult` value object, and three concrete read-only tools. It does NOT deliver the executor (the thing that takes a tool call from Anthropic and dispatches to the right tool, persists the result, and surfaces errors back to the LLM) — that's `phase4-ai-004`. It does NOT deliver the `prepare_send_transaction` tool (the one mutating tool, with PreparedAction lifecycle) — that's `phase4-ai-005`.

The three tools shipped here all read from existing read-side surfaces in other contexts. Per architecture-decisions §"Pragmatic (reads)", direct imports of `<other_context>.application.queries` (or use cases that are query-shaped) are allowed without a gateway wrapper. Each tool is a thin adapter: takes a JSON-schema-validated input, calls the relevant use case for the requesting user, shapes the output as a small dict the LLM can read.

The `Tool` Protocol has three responsibilities:

1. **Self-description** — every tool can return a `ToolDefinition` (name, description, JSON-schema input). The catalog aggregates these definitions and the SSE handler in `phase4-ai-006` includes them in the Anthropic API call's `tools` parameter.
2. **Execution** — every tool has `async execute(input_dict, *, user_id) -> ToolResult`. The executor (`phase4-ai-004`) calls this; this brief just defines the contract and three implementations.
3. **Failure-as-data** — `ToolResult` is a discriminated union: `success: bool`, plus either `data: dict` or `error: ToolError{code, message}`. Errors are NOT exceptions — the LLM sees them as data and can react ("I tried to look up your KYC status but the service is temporarily unavailable; want me to retry?"). Only programmer-error exceptions (validation failures the JSON-schema should have caught, port mis-wiring) propagate.

Why the JSON-schema input rather than typed Python signatures: Anthropic's tool API requires JSON schema. We could maintain Python types and auto-generate the schema (Pydantic does this), but the Anthropic-shaped schema is the canonical contract — generating it is one less translation. Each tool defines its schema as a Python dict literal in its module; a one-shot test validates the dict is a valid JSON schema (via `jsonschema.Draft7Validator.check_schema`).

---

## Architecture pointers

- `architecture-decisions.md` §"AI Assistant" sub-domain catalog (`tools`), §"Pragmatic (reads)" (cross-context read imports allowed), §"Custody invariant enforcement" (the import-linter contract from `phase4-ai-001` AC-02 prevents AI tools from reaching Custody — these three read tools never come close to Custody, but the contract is checked anyway).
- **Layer:** domain (Protocol, VOs, errors) + infra (3 concrete tools — they live in `infra/` because they depend on cross-context use-case imports, which the architecture treats as adapter-level wiring).
- **Packages touched:**
  - `ai/tools/domain/tool.py` (`Tool` Protocol)
  - `ai/tools/domain/value_objects/tool_definition.py` (already declared in `phase4-ai-001`; this brief adds nothing — re-uses)
  - `ai/tools/domain/value_objects/tool_result.py` (`ToolResult{success, data, error}`, `ToolError{code, message}`)
  - `ai/tools/domain/errors.py` (`ToolInputInvalid` — programmer-error case; `ToolUnavailable` — runtime error wrapped into `ToolResult.error`)
  - `ai/tools/domain/catalog.py` (`ToolCatalog` registry)
  - `ai/tools/infra/tools/get_balances.py` (`GetBalancesTool`)
  - `ai/tools/infra/tools/get_recent_transactions.py` (`GetRecentTransactionsTool`)
  - `ai/tools/infra/tools/get_kyc_status.py` (`GetKycStatusTool`)
  - `ai/tools/infra/composition.py` (registers tools in catalog)
- **Reads (cross-context, direct imports allowed by §Pragmatic):**
  - `balances.application.use_cases.GetPortfolio` (Phase 2)
  - `transactions.application.queries.list_user_transactions` (the query backing `GET /api/v1/transactions` from `phase2-transactions-002`)
  - `kyc.application.queries.get_kyc_status` (Phase 3)
- **Writes:** none (this is the read-only catalog).
- **Publishes events:** none.
- **Subscribes to events:** none.
- **New ports introduced:** `Tool` Protocol (`ai/tools/domain/tool.py`).
- **New adapters introduced:** three concrete tools listed above. Plus `FakeTool` test double for `phase4-ai-004`'s executor tests.
- **DB migrations required:** no.
- **OpenAPI surface change:** no.

---

## Acceptance Criteria

- **AC-phase4-ai-003-01:** Given the `Tool` Protocol in `ai/tools/domain/tool.py`, when defined, then it declares: `name: str` (snake_case, regex `^[a-z][a-z0-9_]{1,30}$` — Anthropic constraint), `description: str` (one-line summary the LLM uses to decide when to invoke), `input_schema: Mapping[str, Any]` (a frozen dict matching JSON Schema Draft 7), and `async def execute(self, input: Mapping[str, Any], *, user_id: UUID) -> ToolResult`. The Protocol is checked at runtime via `runtime_checkable` so the catalog can validate registrations.

- **AC-phase4-ai-003-02:** Given the `ToolResult` value object in `ai/tools/domain/value_objects/tool_result.py`, when constructed, then exactly one of these patterns holds: `ToolResult.ok(data: Mapping[str, Any]) -> ToolResult{success=True, data, error=None}` or `ToolResult.failure(error: ToolError) -> ToolResult{success=False, data=None, error}`. Constructing with both `data` and `error`, or neither, raises `ValueError` at construction time. `to_dict()` serialises to `{"success": True, "data": {...}}` or `{"success": False, "error": {"code": "...", "message": "..."}}` — the wire format that goes into `MessageContentBlock.ToolResultBlock.output` in `phase4-ai-002`.

- **AC-phase4-ai-003-03:** Given `GetBalancesTool` in `ai/tools/infra/tools/get_balances.py`, when constructed with `get_portfolio: GetPortfolio` (injected via composition), then: (1) `name == "get_balances"`; (2) `description == "Look up the current balance per chain and asset for the user, with USD conversion. Use this when the user asks about their balance, their funds, or how much they have."`; (3) `input_schema == {"type": "object", "properties": {}, "additionalProperties": False}` (no inputs — the user_id is implicit); (4) `execute({}, user_id=u)` calls `get_portfolio.execute(user_id=u)` and shapes the return as `ToolResult.ok({"wallets": [{"chain", "asset", "amount", "decimals", "usd_value"}, ...], "total_usd": "...", "stale": bool})` — flatter than the REST `/portfolio` response (no nested `balances` array per wallet, just one row per (wallet, asset)). On `BalancesUnavailable` (port failure), returns `ToolResult.failure(ToolError(code="balances_unavailable", message="Balance service temporarily unavailable. Please try again in a moment."))`.

- **AC-phase4-ai-003-04:** Given `GetRecentTransactionsTool` in `ai/tools/infra/tools/get_recent_transactions.py`, when constructed with `list_user_transactions: ListUserTransactions` query, then: (1) `name == "get_recent_transactions"`; (2) `description == "List the user's recent transactions, most recent first. Filterable by status and chain. Use when the user asks about transaction history, recent activity, or a specific transaction."`; (3) `input_schema` allows optional `{"limit": int(1..50), "status": one of confirmed|pending|broadcasting|failed|expired|awaiting_admin|awaiting_totp|approved, "chain": one of ethereum|tron|solana, "before_id": uuid_string}`; (4) `execute(input, user_id=u)` returns `ToolResult.ok({"transactions": [{tx_id, chain, asset, amount, direction, status, value_usd, created_at, broadcast_tx_hash | null}, ...], "next_cursor": uuid | null})`. Defaults: `limit=10`. Per Phase 3's `phase3-ledger-003` AC-07, the underlying query already excludes `is_user_visible=False` postings (e.g., `internal_rebalance`) — the tool inherits this filter automatically.

- **AC-phase4-ai-003-05:** Given `GetKycStatusTool` in `ai/tools/infra/tools/get_kyc_status.py`, when constructed with `get_kyc_status_query`, then: (1) `name == "get_kyc_status"`; (2) `description == "Look up the user's KYC verification tier and per-tier limits. Use when the user asks about identity verification, withdrawal limits, why a withdrawal needs approval, or how to upgrade their tier."`; (3) `input_schema == {"type": "object", "properties": {}, "additionalProperties": False}`; (4) `execute({}, user_id=u)` returns `ToolResult.ok({"tier": "tier_0|tier_1|tier_0_rejected", "review_answer": "GREEN|RED|YELLOW|null", "reject_labels": [str, ...] | null, "limits": {"per_tx_usd": str, "daily_usd": str}, "applicant_started": bool})`. The `limits` come from the same source `phase3-kyc-003`'s `KycTierGateway` reads — but here we read directly via the kyc query (not through the cross-context port; this tool doesn't enforce the limits, only describes them, so direct read is correct).

- **AC-phase4-ai-003-06:** Given `ToolCatalog` in `ai/tools/domain/catalog.py`, when constructed with `tools: Sequence[Tool]`, then: (1) constructor validates every member implements `Tool` Protocol (via `runtime_checkable`) — raises `TypeError` if not; (2) constructor asserts unique `name` across members — raises `ToolNameCollision` if duplicate; (3) `definitions() -> list[ToolDefinition]` returns the schema list in registration order; (4) `find(name: str) -> Tool | None` looks up by name; (5) `names() -> set[str]` returns the registered names. The catalog is immutable post-construction (no `register` method — composition root provides the full list at startup).

- **AC-phase4-ai-003-07:** Given each tool's `input_schema`, when validated via `jsonschema.Draft7Validator.check_schema(tool.input_schema)`, then no exception is raised (i.e., every tool's schema is itself a valid JSON Schema Draft 7 document). A single test `tests/ai/tools/test_all_tool_schemas_valid.py` parametrises over every registered tool and asserts schema validity. This is a static contract — no runtime data involved.

- **AC-phase4-ai-003-08:** Given a tool's `execute(input, user_id=u)`, when `input` does NOT validate against `input_schema` (e.g., extra property, wrong type, missing required field), then the tool **does not silently coerce** — it raises `ToolInputInvalid(tool_name=..., violations=[...])`, NOT `ToolResult.failure`. Rationale: input validation is a programmer-error or LLM-error condition that should be caught at the executor boundary (`phase4-ai-004` AC-02 wraps and surfaces this); leaking it as `ToolResult.failure` would let the LLM see structural validation errors and try to "fix" them, polluting the conversation. Tools assume their input is already valid when `execute` is called.

- **AC-phase4-ai-003-09:** Given the composition `ai/tools/infra/composition.py:configure_tools(container)`, when called from the global composition root after `phase4-ai-001`'s `configure_ai`, then: (1) it instantiates the three concrete tools, injecting their respective query use cases from already-wired contexts; (2) registers a `ToolCatalog` singleton; (3) sub-domain briefs (e.g., `phase4-ai-005` adding `prepare_send_transaction`) extend the catalog by passing an extra tool list to `configure_tools(container, extra_tools=[...])`. The signature is forward-compatible.

- **AC-phase4-ai-003-10:** Given each tool's output shape, when serialised via `to_dict()` and re-loaded, then the result is round-trip stable. Specifically: `Decimal` USD values become strings (per architecture invariant #2 — money never as float); UUIDs become hex strings; datetimes become ISO-8601 UTC strings (`2026-04-27T10:30:00Z`). A single property test parametrises across the three tools' fake-data fixtures, calls `execute`, calls `result.to_dict()`, calls `json.dumps`, calls `json.loads`, and asserts the structure matches the original. Type discipline matters here because the output goes verbatim into a `ToolResultBlock.output` JSONB column (`phase4-ai-002` AC-04) — must be JSON-serialisable.

- **AC-phase4-ai-003-11:** Given the runtime user-scoping invariant, when `execute({}, user_id=u)` is called, then the underlying query is ALWAYS called with `user_id=u`. There is NO code path in any of the three tools that calls a query without `user_id` filter. A static check: `tests/ai/tools/test_user_scoping_static.py` uses `ast.parse` on each tool module and asserts that every call to `*_query.execute(...)` or `*_use_case.execute(...)` includes `user_id=` as a keyword argument. (Brittle but cheap; the architectural alternative would be a runtime tracer in adapter tests, also acceptable.)

- **AC-phase4-ai-003-12:** Given a `FakeTool` in `tests/ai/fakes/fake_tool.py`, when constructed with `name`, `description`, `input_schema`, and `behavior: Callable[[dict, UUID], ToolResult]`, then it implements the `Tool` Protocol exactly. Used by `phase4-ai-004`'s executor tests so they don't depend on real tool implementations. A small test in this brief verifies `FakeTool` constructs and `execute` returns whatever `behavior` says.

---

## Out of Scope

- Tool executor (dispatch, audit logging in `ai.tool_calls`, error mapping): `phase4-ai-004`.
- Mutating tools (`prepare_send_transaction` and the `PreparedAction` aggregate): `phase4-ai-005`.

### Tools mentioned in `claude-code-spec.md §5.4` but NOT shipping in V1

The product spec lists 8 tools in the V1 ambition. This brief delivers 3 read-only tools (`get_balances`, `get_recent_transactions` ≡ ambition's `get_transaction_history`, `get_kyc_status`); `phase4-ai-005` delivers a 4th mutating tool (`prepare_send_transaction`); `phase4-ai-008` delivers a 5th read tool (`search_kb`). The remaining 3 tools from the ambition list are **deferred to V2** with rationale:

| Spec-§5.4 tool name | Status in V1 | Rationale |
|---|---|---|
| `get_balances` | ✓ shipped here (ai-003) | — |
| `get_transaction_history` | ✓ shipped here as `get_recent_transactions` (renamed for clarity) | The rename is intentional; "recent" matches `claude-design-spec §4.2` "Recent activity" UI. |
| `get_kyc_status` | ✓ shipped here (ai-003) | — |
| `prepare_send_transaction` | ✓ shipped in `phase4-ai-005` | — |
| `search_kb` | ✓ shipped in `phase4-ai-008` | RAG over product docs ships as a separate tool in the kb sub-brief. |
| `explain_transaction(tx_hash, chain)` | **deferred to V2** | The LLM can compose an explanation in V1 by calling `get_recent_transactions` (which returns enough fields — direction, amount, status, hash) plus its own reasoning. A dedicated tool would duplicate `get_recent_transactions` for marginal LLM benefit. V2 may add it once we have rich tx-decoding adapters per chain. |
| `estimate_fee(chain, to, amount, asset)` | **deferred to V2** | Fee preview already happens inside `prepare_send_transaction` (`phase4-ai-005`) — the prep card shows the estimated fee, so a separate tool is redundant for the V1 flow. V2 may add a standalone variant for "what would this cost?" queries that don't culminate in a send. |
| `search_transactions(semantic_query)` | **deferred to V2** (substrate ships, tool does not) | The tx-memory pgvector substrate ships in `phase4-ai-007` (`tx_memory_embeddings` table + cross-user-leak property test), but the tool that exposes semantic search to the LLM (`search_my_transaction_history` or similar) is explicitly deferred to V2 per `phase4-ai-007` Out of Scope. V1 lets memory accumulate; V2 adds the consumer tool. |

### Other non-goals

- Tool documentation visible to users (a `/help` page that lists what AI can do): V2.
- Per-user tool feature flags / gating (e.g., disable `get_recent_transactions` for tier_0_rejected users): explicit non-goal — gating is the LLM's responsibility based on `get_kyc_status`'s output, not the tool's.
- A `search_contacts` tool: the Contacts context is not implemented in V1 (per `PHASE2-SUMMARY.md` planning notes). Deferred to V2.
- Localisation of tool descriptions (Ukrainian, Polish, etc.): V2 — V1 ships English only; the LLM can translate user-facing text in its own response.

---

## Dependencies

- **Code dependencies:** `phase4-ai-001` (ToolDefinition VO + ports infra); `phase2-balances-001` (`GetPortfolio` use case); `phase2-transactions-002` (`ListUserTransactions` query — the underlying query for `GET /api/v1/transactions` MUST be exposed as an importable use case in `transactions.application.queries.list_user_transactions`; if it's currently inlined in the router, this brief surfaces it as a separate use case as part of the Tron/Solana extensions in Phase 3 already done so per `phase3-ledger-003` AC-07's filter logic — verify during implementation, lift inline → use case if needed); `phase3-kyc-001` (`get_kyc_status` query).
- **Data dependencies:** none (read-only).
- **External dependencies:** `jsonschema>=4.21` for schema validation.

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/ai/tools/domain/test_tool_protocol.py` — runtime-checkable conformance (a class missing `execute` is rejected). Covers AC-01.
- [ ] **Domain unit tests:** `tests/ai/tools/domain/test_tool_result.py` — `ok` / `failure` constructors, invalid construction, `to_dict` round-trip on basic shapes. Covers AC-02.
- [ ] **Domain unit tests:** `tests/ai/tools/domain/test_catalog.py` — registration, name collision, `definitions()`, `find()`, immutability. Covers AC-06.
- [ ] **Static schema validity:** `tests/ai/tools/test_all_tool_schemas_valid.py` — covers AC-07.
- [ ] **Static user-scoping:** `tests/ai/tools/test_user_scoping_static.py` — covers AC-11.
- [ ] **Adapter tests (with fakes for cross-context):** `tests/ai/tools/infra/test_get_balances_tool.py` — happy path, port-failure → `ToolResult.failure`, output round-trip. Covers AC-03 + AC-10.
- [ ] **Adapter tests:** `tests/ai/tools/infra/test_get_recent_transactions_tool.py` — happy path with various filter combinations, pagination, output round-trip, `is_user_visible=False` postings excluded (regression-tests `phase3-ledger-003` AC-07). Covers AC-04 + AC-10.
- [ ] **Adapter tests:** `tests/ai/tools/infra/test_get_kyc_status_tool.py` — tier_0, tier_1, tier_0_rejected with reject_labels, applicant-not-started case. Covers AC-05 + AC-10.
- [ ] **Property tests:** `tests/ai/tools/infra/test_tool_output_serialization_properties.py` — for each tool's fake-data fixture, `json.loads(json.dumps(result.to_dict()))` preserves structure. Covers AC-10.
- [ ] **Input validation:** `tests/ai/tools/infra/test_input_validation.py` — for each tool, calling `execute` with a malformed input raises `ToolInputInvalid` (NOT `ToolResult.failure`). Covers AC-08.
- [ ] **Composition tests:** `tests/ai/tools/test_composition.py` — `configure_tools(container)` registers all three; `extra_tools` parameter accepts additional tools and registers them. Covers AC-09.
- [ ] **Fake-tool test:** `tests/ai/fakes/test_fake_tool.py` — covers AC-12.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All listed test categories implemented and passing locally.
- [ ] `import-linter` contracts pass — and a sub-check: `ai.tools.infra` imports from `balances.application.use_cases`, `transactions.application.queries`, `kyc.application.queries` are explicit and limited (the import-linter "AI never imports Custody" contract still holds).
- [ ] `mypy --strict` passes for `vaultchain.ai.tools.*`.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass (`ai/tools/domain/` ≥ 95%, `ai/tools/infra/` ≥ 90%).
- [ ] OpenAPI schema unchanged (no API surface in this brief).
- [ ] One new error code (`ai.tool_input_invalid` — for `ToolInputInvalid`, programmer-error class) registered + visible in `errors-reference.md`.
- [ ] One new port declared (`Tool` Protocol) with fake `FakeTool` in `tests/ai/fakes/`.
- [ ] No new migration.
- [ ] No new domain events.
- [ ] If `ListUserTransactions` query was previously inlined in `transactions/delivery/router.py`, it is lifted into `transactions/application/queries/list_user_transactions.py` as part of this PR (small refactor; documented in commit body).
- [ ] Single PR. Conventional commit: `feat(ai/tools): read-only catalog (3 tools) [phase4-ai-003]`.
- [ ] PR description: a small table — `name | description | input_schema_summary | reads_from`.

---

## Implementation Notes

- **JSON-schema source of truth.** The Anthropic API expects JSON-schema-shaped tool definitions verbatim. We hand-author them as Python dict literals. Don't reach for Pydantic-to-JSONschema-generation here — the dict is the spec, and decoupling from Pydantic keeps the domain Pydantic-free per the architecture's domain-purity rule.
- **`get_balances` returns flatter shape than `/portfolio`.** The REST endpoint's `wallets[].balances[]` nesting is good for UI but verbose for the LLM. Flatten to one row per (wallet, asset) — easier for the LLM to summarise.
- **`get_recent_transactions` description tells the LLM about pagination** ("`before_id` to fetch older"). Anthropic's tool selection uses descriptions liberally; precise descriptions reduce wrong-tool calls.
- **`get_kyc_status` returns Decimal-as-string for `limits.per_tx_usd` / `daily_usd`.** Architecture invariant #2 — money never as float. The LLM will format these for display in its assistant message.
- **`ToolError.code` is dotted snake_case** matching the architecture's structured-error-code convention. `balances_unavailable`, `transactions_unavailable`, `kyc_unavailable` — these are not domain errors registered in `errors-reference.md` because they're tool-result data, not HTTP error responses. Don't pollute the error registry with tool errors.
- **Catalog ordering = registration ordering.** Anthropic doesn't care about ordering, but stable ordering helps test fixtures and snapshot tests. `ToolCatalog` keeps an internal list; `definitions()` returns it as `tuple` (immutable).
- **The `tools/infra/composition.py` extra_tools parameter** is the extension seam for `phase4-ai-005` to add `prepare_send_transaction` without modifying this brief's wiring.

---

## Risk / Friction

- **`ListUserTransactions` may not exist as a clean use case yet.** Phase 2/3 may have inlined the query in the FastAPI router. The Done Definition allows lifting it — small refactor, no new behaviour. Flag in PR; reviewer checks no regression in `GET /api/v1/transactions` responses.
- **Cross-context import discipline.** `ai/tools/infra/` imports from `balances.application`, `transactions.application`, `kyc.application` — all read-side. The architecture explicitly allows this (§"Pragmatic reads"). A reviewer might still raise an eyebrow; the inline comment in each tool's module quotes the architecture section to pre-empt.
- **The `static user-scoping check` (AC-11) is brittle to refactors.** If a tool starts using a wrapper helper (e.g., `_call_query(query, user_id)`), the AST regex won't see `user_id=` directly. Document this in the test as a known limitation; a fallback is a runtime trace in the adapter tests (also acceptable). Mention in the implementation note that "if you refactor, update the static check".
- **Tool descriptions are user-visible-via-LLM.** A poorly worded description can cause the LLM to hallucinate a use case ("the user asked for X, get_balances description says it does Y, let me invoke it"). Done Definition requires the descriptions to ship as exactly-worded — no wordsmithing during review without re-running Tier-3 evals (per ADR-006). `phase4-evals-001` will exercise tool selection across realistic user prompts.
- **The architecture mentions `search_contacts` in §"Tools" sub-domain catalog.** A reviewer reading the architecture and looking for this tool will not find it. Out-of-Scope explicitly notes the Contacts deferral; the architecture doc itself is fine because it describes the V1 ambition, the brief realises the V1 actual.
