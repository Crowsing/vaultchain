---
ac_count: 11
blocks:
- phase4-ai-002
- phase4-ai-003
- phase4-ai-004
- phase4-ai-005
- phase4-ai-006
- phase4-ai-007
- phase4-ai-008
- phase4-ai-009
complexity: L
context: ai
depends_on:
- phase1-shared-003
- phase1-shared-005
- phase1-deploy-001
estimated_hours: 4
id: phase4-ai-001
phase: 4
sdd_mode: strict
state: ready
title: AI infrastructure (Anthropic + Gemini embeddings adapters + pgvector + ai schema
  bootstrap)
touches_adrs:
- ADR-010
---

# Brief: phase4-ai-001 — AI infrastructure (Anthropic + Gemini embeddings adapters + pgvector + ai schema bootstrap)


## Context

This brief lays the foundation for the entire AI Assistant context. Nothing user-visible ships here — what ships is the package skeleton, the `ai` Postgres schema, the two infrastructure adapters every later brief consumes (Anthropic LLM client wrapper and Google Gemini embeddings client wrapper), the `pgvector` extension installation, the import-linter contracts that enforce invariant #1 ("AI never imports Custody") and the ports-only-into-infra discipline, and the composition-root wiring so later briefs can plug in domain code without touching infra plumbing.

The architecture (Section 1) declares AI as the only context with internal sub-domains: `chat`, `tools`, `suggestions`, `memory`, plus a `shared` and `infra` layer common across them. The package layout (Section 2) is already specified. This brief realises that layout as empty-but-typed packages with `__init__.py` files and the two adapters that all sub-domains will share. Sub-domain code arrives in subsequent briefs.

Why a single foundation brief vs piecemeal: the LLM and embeddings adapters share an HTTP client pattern (retry, timeout, structured error mapping, Sentry breadcrumb), share a config object, and need the same composition-root entrypoint. Splitting them creates needless coordination overhead. pgvector setup likewise belongs in one place — the migration that creates the `ai` schema and installs the extension is a single atomic Alembic revision. Per-table migrations live in their owning briefs (chat-002 owns `ai.conversations`/`ai.messages`, memory-007 owns `ai.tx_memory_embeddings`, etc.).

ADR-010 is drafted here because the embedding-model choice is the single most consequential decision for the memory and RAG sub-systems — it affects the table schema (`VECTOR(N)`), the per-row storage cost, and the latency/quality trade-off. The architecture-decisions doc says `text-embedding-3-small or similar` and shows `VECTOR(1536)` as illustrative; ADR-010 is the binding specification for Phase 4: **`gemini-embedding-001` at 768 dims** via Matryoshka truncation, with `task_type='RETRIEVAL_DOCUMENT'` on writes and `task_type='RETRIEVAL_QUERY'` on reads. The pgvector index strategy (`ivfflat` parameters) and the per-user-scoping enforcement live in `phase4-ai-007` (the brief that actually creates the memory table and writes to it) — keeping ADR-010 narrow to "model + dim" so the decision is reviewable in <60 seconds.

---

## Architecture pointers

- `architecture-decisions.md` §"AI Assistant" sub-domain catalog (Section 1 lines 52–56), §"Vector store" (Section 3, the `ai.tx_memory_embeddings` shape — note the `VECTOR(1536)` there is illustrative, ADR-010 binds the actual dim to 768), §"Layer model" (Section 2, `ai/` package layout), §"Custody invariant enforcement" (the import-linter contract).
- **Layer:** infra (HTTP clients, migrations) + shared (config + DI wiring).
- **Packages created (empty bodies, typed `__init__.py` with `__all__`):**
  - `ai/__init__.py`
  - `ai/chat/{domain,application}/__init__.py`
  - `ai/tools/{domain,application,infra}/__init__.py`
  - `ai/suggestions/{domain,application,infra}/__init__.py`
  - `ai/memory/{domain,application,infra}/__init__.py`
  - `ai/shared/{domain,application}/__init__.py` (will host `ToolCall` VO, `PreparedAction` aggregate base in later briefs)
  - `ai/infra/__init__.py` (this brief populates it)
- **Packages populated by THIS brief:**
  - `ai/infra/anthropic_client.py` — async wrapper over `anthropic.AsyncAnthropic`, with retry/timeout/error-map.
  - `ai/infra/gemini_embeddings_client.py` — async wrapper over `google-genai`'s `client.aio.models.embed_content`.
  - `ai/infra/config.py` — `AISettings` Pydantic settings.
  - `ai/infra/composition.py` — `configure_ai(container, settings)` DI wiring.
  - `ai/infra/migrations/001_ai_schema.py` (Alembic) — creates `ai` schema, installs `pgvector` extension, no tables yet.
- **Reads:** none from other contexts.
- **Writes:** none to other contexts.
- **Publishes events:** none.
- **Subscribes to events:** none.
- **New ports introduced:**
  - `ai.shared.domain.ports.LlmClient` (Protocol; methods: `stream_message(*, system, messages, tools, max_tokens) -> AsyncIterator[StreamEvent]`, `complete(*, system, messages, tools, max_tokens) -> CompleteResponse`).
  - `ai.shared.domain.ports.EmbeddingsClient` (Protocol; methods: `embed_one(text, *, task_type) -> list[float]`, `embed_batch(texts, *, task_type) -> list[list[float]]`).
- **New adapters introduced:** `AnthropicLlmClient` (implements `LlmClient`), `GeminiEmbeddingsClient` (implements `EmbeddingsClient`). Plus `FakeLlmClient` and `FakeEmbeddingsClient` test doubles in `tests/ai/fakes/`.
- **DB migrations required:** yes — single Alembic revision creates `ai` schema and installs `pgvector` extension; per-table migrations live in their respective briefs.
- **OpenAPI surface change:** no.
- **Import-linter contracts added to `pyproject.toml`:**
  - `name = "AI never imports Custody"; type = "forbidden"; source_modules = ["vaultchain.ai"]; forbidden_modules = ["vaultchain.custody"]`
  - `name = "AI sub-domains do not import ai.infra"; type = "forbidden"; source_modules = ["vaultchain.ai.chat", "vaultchain.ai.tools", "vaultchain.ai.suggestions", "vaultchain.ai.memory"]; forbidden_modules = ["vaultchain.ai.infra"]`
  - `name = "ai.infra does not import any sub-domain"; type = "forbidden"; source_modules = ["vaultchain.ai.infra"]; forbidden_modules = ["vaultchain.ai.chat", "vaultchain.ai.tools", "vaultchain.ai.suggestions", "vaultchain.ai.memory"]`

---

## Acceptance Criteria

- **AC-phase4-ai-001-01:** Given the `ai/` package tree, when `python -c "import vaultchain.ai; import vaultchain.ai.chat.domain; import vaultchain.ai.tools.domain; import vaultchain.ai.suggestions.domain; import vaultchain.ai.memory.domain; import vaultchain.ai.shared.domain; import vaultchain.ai.infra"` is run, then all imports succeed with no side effects (no DB connection, no HTTP client constructed, no env-var read at import time). Each `__init__.py` has an explicit `__all__` listing only what is exported (initially empty for sub-domains, populated for `ai.infra` and `ai.shared.domain.ports`).

- **AC-phase4-ai-001-02:** Given the import-linter contract "AI never imports Custody", when a synthesised test fixture adds `from vaultchain.custody import anything` inside any `ai/` module, then `lint-imports` reports a violation and exits non-zero. A regression test in `tests/architecture/test_import_contracts.py` verifies this by running `lint-imports` programmatically against a temp-copy with the violation injected, and asserting failure.

- **AC-phase4-ai-001-03:** Given the import-linter contract "AI sub-domains do not import ai.infra", when a test introduces `from vaultchain.ai.infra.anthropic_client import AnthropicLlmClient` inside `ai/chat/application/`, then `lint-imports` fails. Composition root (`ai/infra/composition.py`) is the only place wiring concrete adapters to ports — verified by AC-09. The reverse contract (`ai.infra` may not import sub-domains) is also asserted with a synthesised reverse violation.

- **AC-phase4-ai-001-04:** Given the Alembic migration `001_ai_schema.py`, when applied against an empty test database, then: (1) `ai` schema exists (`SELECT 1 FROM information_schema.schemata WHERE schema_name = 'ai'` returns 1); (2) `pgvector` extension is installed (`SELECT 1 FROM pg_extension WHERE extname = 'vector'` returns 1); (3) no tables created. Migration is idempotent — applying twice is a no-op via `CREATE SCHEMA IF NOT EXISTS` and `CREATE EXTENSION IF NOT EXISTS vector`. Down-migration drops `ai` schema only if empty (CASCADE is forbidden — explicit fail if sub-domain tables are present, ensuring brief-author discipline catches forgotten down-migrations).

- **AC-phase4-ai-001-05:** Given the `LlmClient` Protocol in `ai/shared/domain/ports.py`, when defined, then it declares: `async def stream_message(*, system: str, messages: list[ChatMessageInput], tools: list[ToolDefinition], max_tokens: int) -> AsyncIterator[StreamEvent]` and `async def complete(*, system, messages, tools, max_tokens) -> CompleteResponse`. `StreamEvent` is a discriminated union (`MessageStart | ContentDelta | ToolUseStart | ToolUseInputDelta | ToolUseStop | MessageStop | StreamError`) — these mirror Anthropic's stream events but are our domain types so we never import the SDK's types into domain code. `ChatMessageInput`, `ToolDefinition`, `CompleteResponse` are Pydantic-free dataclasses (frozen) defined in `ai/shared/domain/value_objects/`.

- **AC-phase4-ai-001-06:** Given the `AnthropicLlmClient` adapter in `ai/infra/anthropic_client.py`, when instantiated with `AISettings`, then: (1) it constructs a single shared `anthropic.AsyncAnthropic` client (singleton-per-process); (2) `stream_message` translates Anthropic SDK stream events into our domain `StreamEvent` types (mapping table documented inline as a comment block — `RawMessageStartEvent → MessageStart`, `RawContentBlockStartEvent(type=text) → (no event, sets state)`, `RawContentBlockDeltaEvent(delta=text_delta) → ContentDelta`, `RawContentBlockStartEvent(type=tool_use) → ToolUseStart`, `RawContentBlockDeltaEvent(delta=input_json_delta) → ToolUseInputDelta`, `RawContentBlockStopEvent → ToolUseStop` (when in tool-use state), `RawMessageStopEvent → MessageStop`); (3) timeouts: connect 5s, read 60s, stream-idle 30s; (4) retries: 3 attempts on `anthropic.APIConnectionError` / `anthropic.RateLimitError` / `anthropic.InternalServerError` with exponential backoff (0.5s, 1s, 2s); (5) every error pushes a Sentry breadcrumb with `{model, request_id, attempt_number, error_class}` — **no message contents, no tool inputs, no tool results** (privacy invariant); (6) on permanent failure, raises `LlmUnavailableError(code="llm.unavailable")` from `ai/shared/domain/errors.py`.

- **AC-phase4-ai-001-07:** Given the `EmbeddingsClient` Protocol and the `GeminiEmbeddingsClient` adapter, when invoked, then: (1) `embed_one("hello", task_type=TaskType.RETRIEVAL_DOCUMENT)` returns a `list[float]` of length exactly `EMBEDDING_DIM` (default 768); (2) `embed_batch(["a", "b", "c"], task_type=TaskType.RETRIEVAL_QUERY)` returns a list of 3 lists, each length 768, in the same order as inputs; (3) the adapter calls `client.aio.models.embed_content(model=settings.AI_MODEL_EMBEDDING, contents=texts, config=types.EmbedContentConfig(output_dimensionality=settings.EMBEDDING_DIM, task_type=task_type.value))`; (4) timeouts/retries match the Anthropic adapter's pattern; (5) batch size is capped at 100 (above this, the adapter chunks internally); (6) on permanent failure, raises `EmbeddingsUnavailableError(code="embeddings.unavailable")`. `TaskType` is a domain enum (`RETRIEVAL_DOCUMENT`, `RETRIEVAL_QUERY`, `SEMANTIC_SIMILARITY`) — write paths in `phase4-ai-007` use `RETRIEVAL_DOCUMENT`, retrieval queries in `phase4-ai-008` use `RETRIEVAL_QUERY`. The choice of `gemini-embedding-001` (vs `gemini-embedding-2`, OpenAI `text-embedding-3-small`, local sentence-transformers, Voyage) and the 768 dimension is documented in ADR-010.

- **AC-phase4-ai-001-08:** Given `tests/ai/fakes/fake_llm_client.py` and `tests/ai/fakes/fake_embeddings_client.py`, when used in application tests, then: `FakeLlmClient` accepts a pre-recorded mapping `{cassette_key → list[StreamEvent]}` (default cassette key derived from a hash of the input) and replays them; `FakeEmbeddingsClient` returns deterministic vectors derived from a hash of the input text — `numpy.random.default_rng(int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], 'big')).standard_normal(EMBEDDING_DIM)` then L2-normalised. Both fakes implement the Protocol exactly. Behavior tested: `FakeLlmClient.stream_message` yields the expected events; `FakeEmbeddingsClient.embed_one(x) == FakeEmbeddingsClient.embed_one(x)` (determinism), `embed_one(x) != embed_one(y)` for distinct `x`/`y`, vectors are unit-norm.

- **AC-phase4-ai-001-09:** Given the composition root, when application starts, then: `LlmClient` resolves to `AnthropicLlmClient(settings)` in dev/prod and to `FakeLlmClient` under `pytest`. `EmbeddingsClient` resolves analogously. The wiring is in a single `ai/infra/composition.py:configure_ai(container, settings)` function called from the global composition root — sub-domain briefs add their own `configure_<subdomain>(container)` calls without touching this brief's wiring. The pytest-detection uses the established pattern from `phase1-shared-003` (env var `RUNNING_UNDER_PYTEST=1` set by `conftest.py`).

- **AC-phase4-ai-001-10:** Given a smoke contract test against the Anthropic client (recorded with vcrpy), when `stream_message(system="You are a test bot.", messages=[ChatMessageInput(role="user", content="say 'pong'")], tools=[], max_tokens=20)` is invoked, then the cassette captures: (1) one `MessageStart`; (2) one or more `ContentDelta` events; (3) one `MessageStop` with `stop_reason='end_turn'`; (4) total elapsed under the timeout; (5) no error events. The cassette is committed under `tests/ai/cassettes/anthropic_smoke.yaml`. A parallel smoke cassette exists for Gemini embeddings: `tests/ai/cassettes/gemini_embeddings_smoke.yaml` capturing one `embed_one` call returning a 768-vector. Re-recording instructions are in `docs/runbook.md`.

- **AC-phase4-ai-001-11:** Given the structured-error registry, when `LlmUnavailableError` and `EmbeddingsUnavailableError` are added to `shared/domain/errors.py` and propagated into the auto-generated `errors-reference.md`, then both have entries with `code`, `http_status: 503`, human description ("AI assistant temporarily unavailable, please retry in a moment"), and `documentation_url` per the architecture's error-envelope contract (Section 4). CI's drift check on `errors-reference.md` passes.

- **AC-phase4-ai-001-12:** Given **ADR-010 — Embedding model and dimension choice**, when committed, then `docs/decisions/ADR-010-embedding-model-and-dimension.md` exists with three sections: **Context** (we need an embedding model for transaction memory and product-doc RAG; candidates considered: Google `gemini-embedding-001`, Google `gemini-embedding-2`, OpenAI `text-embedding-3-small`, local `sentence-transformers/BAAI/bge-base`, Voyage `voyage-3.5`); **Decision** (Google `gemini-embedding-001` at **768 dims** via Matryoshka truncation, with `task_type='RETRIEVAL_DOCUMENT'` on writes and `'RETRIEVAL_QUERY'` on reads; this binds the table schema to `VECTOR(768)` — supersedes the illustrative `VECTOR(1536)` in `architecture-decisions.md` §"Vector store"); **Consequences** — *acceptable*: Google is the project's existing embeddings vendor (no third vendor added beyond Anthropic for chat); MTEB multilingual leader (68.32) — relevant because user inputs may be non-English; 768 dims via MRL scores 67.99 vs 68.16 at 3072 (Google's published benchmark), a 75% storage saving for ~0.3% quality drop, the obvious production trade; pricing $0.15/MTok ($0.075 batch) — at V1 corpus scale (~10k tx summaries × 50 tokens + ~500 doc chunks × 500 tokens) total embedding spend is sub-$1; *concerning*: `gemini-embedding-001` and `gemini-embedding-2` produce **incompatible** embedding spaces — switching later requires re-embedding the full corpus (acceptable: corpus is small, V2 migration is the right time to switch); *trade-off vs OpenAI*: OpenAI `text-embedding-3-small` is roughly 7-8× cheaper per token (~$0.02/MTok vs Gemini's $0.15/MTok) but English-leaning; we pay slightly more for multilingual quality and avoid adding a second AI vendor; *trade-off vs local sentence-transformers*: local models eliminate a vendor and cost but add CPU/memory load to the API process and require a model-cache strategy — defensible only if cost dominates (it doesn't at our scale); *explicit non-decisions* (deferred to phase4-ai-007 ADR or implementation): the `ivfflat` index parameters (`lists`, `probes`), the per-query `WHERE user_id = $1` enforcement strategy, and the property test guarding cross-user-leak prevention all live in `phase4-ai-007` because they belong with the table that uses them. The ADR explicitly addresses: "why not gemini-embedding-2?" → "GA only 4 days at brief authoring time; spec stability for V1 favours `001`; migration path to `2` is documented as a re-embed job in V2 backlog." Reviewer's first-30-second read should land on "this person knows production embedding trade-offs" — model choice + dim trade + vendor count + RAG-specific task_type all visible.

---

## Out of Scope

- Any sub-domain code (`chat`, `tools`, `suggestions`, `memory`): each has its own brief.
- Per-table migrations (`ai.conversations`, `ai.messages`, `ai.tx_memory_embeddings`, etc.): created in the brief that owns the table.
- Tool definitions or executor logic: `phase4-ai-003` / `phase4-ai-004`.
- SSE protocol, chat endpoints, prep cards: `phase4-ai-005` / `phase4-ai-006`.
- Memory writer / RAG retrieval / pgvector index parameters / per-user-scoping enforcement: `phase4-ai-007` / `phase4-ai-008`.
- Live evals harness (Tier 3 per ADR-006): `phase4-evals-001`.
- Frontend chat panel: `phase4-web-008`.
- Column-level encryption of chat content: V2 explicitly per architecture §"Vector store" closing paragraph.
- Migration from `gemini-embedding-001` to `gemini-embedding-2`: V2 (re-embed job).

---

## Dependencies

- **Code dependencies:** `phase1-shared-003` (DI container, UoW); `phase1-shared-004` (Outbox publisher — used by later AI briefs, not this one, but the wiring pattern is established here); `phase1-shared-005` (Sentry + structlog hooks + DomainError → HTTP); bootstrap-provided Pydantic Settings base class.
- **Data dependencies:** Postgres reachable; superuser privilege required at migration time to install `CREATE EXTENSION pgvector` (Neon supports this; documented in `docs/runbook.md` infra section).
- **External dependencies:** `anthropic` Python SDK pinned in `pyproject.toml` (`>=0.39`); `google-genai` Python SDK (`>=1.73` — minimum version for current embedding behavior per Google cookbook); `pgvector` Python client (`>=0.3`, used by later briefs but pinned now); env vars `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, optional overrides `AI_MODEL_CHAT` (default `claude-sonnet-4-6`; the previously-default `claude-sonnet-4-20250514` is now labelled "deprecated" by Anthropic — still resolves but the migration guide recommends moving to `claude-sonnet-4-6` or `claude-opus-4-7`), `AI_MODEL_EMBEDDING` (default `gemini-embedding-001`), `AI_MAX_TOKENS` (default 4096), `AI_TIMEOUT_SECONDS` (default 60), `EMBEDDING_DIM` (default 768).

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/ai/shared/domain/test_value_objects.py` — `ChatMessageInput`, `ToolDefinition`, `CompleteResponse`, `StreamEvent` discriminated union construction + invalid-construction raises; `TaskType` enum exhaustiveness. Covers AC-05.
- [ ] **Adapter tests (vcrpy cassette):** `tests/ai/infra/test_anthropic_client.py` — `stream_message_smoke` (covers AC-06, AC-10 via cassette `anthropic_smoke.yaml`); `stream_translates_tool_use_events` (using a synthesised cassette with a tool_use sequence); `retries_on_rate_limit` (synthesised 429 cassette); `permanent_failure_raises_llm_unavailable_error`; `sentry_breadcrumb_redacts_message_contents` (asserts breadcrumb metadata excludes message bodies).
- [ ] **Adapter tests (vcrpy cassette):** `tests/ai/infra/test_gemini_embeddings_client.py` — `embed_one_returns_correct_dim` (covers AC-07 + AC-10 via `gemini_embeddings_smoke.yaml`); `embed_batch_preserves_order`; `chunks_above_100`; `respects_task_type_parameter` (assert request body contains `task_type` field via cassette inspection); `permanent_failure_raises_embeddings_unavailable_error`.
- [ ] **Migration tests:** `tests/ai/infra/test_migration_001_ai_schema.py` — applies migration to ephemeral testcontainers Postgres; asserts schema + extension exist; applies twice (idempotent); rolls back; rolls back twice (idempotent); rollback fails-loud if `ai.*` tables exist (uses a temp test table to verify the safeguard). Covers AC-04.
- [ ] **Architecture tests:** `tests/architecture/test_import_contracts.py` — synthesises violations in temp files and runs `lint-imports` programmatically; asserts failure for each of the three new contracts. Covers AC-02, AC-03.
- [ ] **Fake-double tests:** `tests/ai/fakes/test_fake_llm_client.py`, `test_fake_embeddings_client.py` — covers AC-08 including L2-norm property and determinism property (hypothesis-driven on random unicode strings, asserts norm ≈ 1 within 1e-6).
- [ ] **Composition tests:** `tests/ai/test_composition.py` — `configure_ai(container, test_settings)` resolves `LlmClient` to `FakeLlmClient` and `EmbeddingsClient` to `FakeEmbeddingsClient` under `RUNNING_UNDER_PYTEST=1`; in a non-pytest profile (env var unset, simulated via `monkeypatch.delenv`), resolves to real adapters (without instantiating real clients — verified via `isinstance` after wiring, no actual HTTP). Covers AC-09.
- [ ] **Smoke import test:** `tests/ai/test_package_imports.py` — verifies AC-01 (no side effects at import).
- [ ] **Errors-reference drift:** existing CI gate (architecture-decisions §"Error envelope") catches any new error class missing from the registry. Covers AC-11.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All listed test categories implemented and passing locally.
- [ ] `import-linter` contracts pass — and the three new contracts above are checked into `pyproject.toml`.
- [ ] `mypy --strict` passes for `vaultchain.ai.*`.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass (`ai/infra/` ≥ 90%, `ai/shared/domain/` ≥ 95% — domain VOs are crypto-adjacent in the broader sense that the LLM port boundary is a key invariant).
- [ ] OpenAPI schema unchanged (no API surface in this brief).
- [ ] Two new error codes (`llm.unavailable`, `embeddings.unavailable`) registered + visible in generated `errors-reference.md`.
- [ ] Two new ports declared (`LlmClient`, `EmbeddingsClient`) with fakes in `tests/ai/fakes/`.
- [ ] One new Alembic revision committed + applied + rolled-back tested.
- [ ] **ADR-010 drafted and committed.**
- [ ] `docs/runbook.md` updated with: pgvector install one-liner, re-recording cassettes procedure (`pytest --record-mode=once`), env vars for AI model overrides, note that `EMBEDDING_DIM` cannot be changed without a re-embed migration.
- [ ] `pyproject.toml`: `anthropic>=0.39`, `google-genai>=1.73`, `pgvector>=0.3` added.
- [ ] Single PR. Conventional commit: `feat(ai): foundation — adapters, schema, ports, ADR-010 [phase4-ai-001]`.
- [ ] PR description: a one-page diagram showing `LlmClient` / `EmbeddingsClient` ports and the two concrete adapters + the empty sub-domain packages waiting for next briefs.

---

## Implementation Notes

- The `StreamEvent` discriminated union is the most subtle piece. Mirror Anthropic's stream events but **rename**: domain code never sees Anthropic's class names. The mapping table belongs at the top of `anthropic_client.py` as a comment block.
- Use `anthropic.AsyncAnthropic` (not the sync client). The streaming API is `async with client.messages.stream(...) as stream: async for event in stream:`.
- Don't import `anthropic.types.*` into domain. The adapter is the translation boundary.
- For Gemini: `from google import genai; client = genai.Client(api_key=settings.GOOGLE_API_KEY); await client.aio.models.embed_content(model=..., contents=..., config=types.EmbedContentConfig(output_dimensionality=settings.EMBEDDING_DIM, task_type=task_type.value))`. The async path is `client.aio.*`.
- `pgvector` Python client (`pgvector.sqlalchemy.Vector`) is needed in later briefs, not this one — but pin it now to keep `pyproject.toml` consistent.
- Migration uses `op.execute("CREATE EXTENSION IF NOT EXISTS vector")`. Some Postgres deployments require this in a dedicated migration; Neon docs confirm support.
- The fakes are deterministic — embedding test fakes derive vectors from `hashlib.sha256(text.encode()).digest()` then unpack via `numpy.random.default_rng(seed).standard_normal(EMBEDDING_DIM)` and L2-normalise. This makes property tests in `phase4-ai-007` / `phase4-ai-008` reproducible.
- Don't add a "ping" or "health-check" endpoint here — that's `phase1-shared-005`'s territory.
- Sentry breadcrumb redaction: never include `messages` array contents, tool inputs, tool results, or embedding inputs in error metadata. Architecture is explicit that AI chat content can contain PII.
- The Gemini SDK's response shape is `result.embeddings: list[ContentEmbedding]` where each has `.values: list[float]`. The adapter unpacks `.values` per item.

---

## Risk / Friction

- **Anthropic SDK API churn.** The SDK bumps minor versions weekly. Pinning `>=0.39` is forward-tolerant; if a breaking change lands, the adapter is the only place that needs updating — domain code is insulated.
- **`google-genai` SDK is relatively new** (renamed/replaced legacy `google-generativeai` in 2025). Pin `>=1.73` per Google's official cookbook minimum for the current embedding API. Documented in runbook.
- **Embedding model lock-in.** `gemini-embedding-001` and `gemini-embedding-2` are not interchangeable — different vector spaces. ADR-010 makes this explicit; V2 backlog includes "re-embed corpus when migrating embedding model" as a known operation. Acceptable for V1 portfolio scope; a real product would have an embedding-model-version column on every embedding row to support live A/B migration. Worth mentioning in the ADR Risks section if the reviewer asks.
- **pgvector availability.** Neon supports it; if the deploy moves to a Postgres flavour without pgvector, this brief breaks. Documented in runbook as a hosting prerequisite.
- **Fake LLM determinism vs realism.** Pre-recorded events in fakes are precise but boring. Tier-2 SSE protocol tests (per ADR-006) use real recorded conversations from Anthropic; that's where realism enters. Fakes here are for application-layer logic only.
- **Migration ordering.** This migration must run before any `ai.*` table migration. Alembic's revision graph handles this naturally — revision IDs are generated chronologically.
- **`task_type` is a Gemini-specific quality optimization.** The port abstraction accepts it as a parameter so callers can choose; if we later swap to a model that doesn't support task_type (OpenAI doesn't), the parameter becomes a no-op in that adapter — acceptable, the port contract documents `task_type` as "advisory; adapters may ignore."
