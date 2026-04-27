---
ac_count: 11
blocks:
- phase4-ai-007
- phase4-evals-001
complexity: M
context: ai
depends_on: []
estimated_hours: 4
id: phase4-ai-008
phase: 4
sdd_mode: strict
state: ready
title: RAG over product docs (`ai.kb_embeddings` + retrieval port + ingestion CLI)
touches_adrs: []
---

# Brief: phase4-ai-008 — RAG over product docs (`ai.kb_embeddings` + retrieval port + ingestion CLI)


## Context

This brief realises the second half of the **memory** sub-domain: static RAG over product documentation. The use case is a future "AI assistant explains how to use the product" surface — when a user asks "how do I withdraw to a contract address?" or "what's the difference between cold and hot tier?", the retrieval finds the most relevant doc snippets and (V2) injects them into the chat system prompt for grounded answers.

**What ships in V1:**

1. The `ai.kb_embeddings` table — schema declared in `architecture-decisions.md` §"Vector store" (line 391: "A parallel `ai.kb_embeddings` table indexes product docs and FAQ for static RAG.").
2. ivfflat index parameters appropriate to a small static corpus (~500 chunks expected from `docs/product/` Markdown files).
3. The `KbRetriever.search(query_text, *, limit=5, min_similarity=0.65)` port — global search (no user-scoping, kb is shared product knowledge), with a similarity floor that returns empty rather than poor matches.
4. An ingestion CLI: `vaultchain kb ingest <docs_path>` walks a directory, finds `.md` files, chunks them, embeds via Gemini, persists to `ai.kb_embeddings`. Idempotent on `(source_path, chunk_index)` UNIQUE — re-running on an updated doc produces clean updates without duplicates.
5. Six baseline product-doc Markdown files committed under `docs/product/`: a starting corpus.

**What does NOT ship:**

- Chat-context injection (RAG-augmented system prompt): V2; the architecture mentions this as the eventual consumer; V1 ships the substrate.
- An admin UI for managing kb chunks: V2; ingestion is CLI-only in V1.
- Multi-language docs (Ukrainian, Russian translations of product docs): V2; V1 ships English-only docs but the embedding model is multilingual — Ukrainian queries against English docs work tolerably (Gemini's MTEB multilingual leadership is a key reason for the model choice in ADR-010).
- Document versioning / history: V2; V1 simply re-ingests.
- Real-time doc reload: V2; V1 requires explicit CLI invocation after editing docs.
- A dedicated "search docs" tool the LLM can invoke: V2 surface; this brief delivers the port that a V2 tool would wrap, but the tool itself is out of scope.

**Why no cross-user-leak property test like `phase4-ai-007`:**

`ai.kb_embeddings` rows are global by design — every user retrieves from the same corpus. The vulnerability category that the `phase4-ai-007` test guards (vector search bleeding across user boundaries) does not apply here because there are no user boundaries to bleed across. The architecture is deliberate: tx memory is per-user (sensitive), kb is global (public product info). Conflating them would either over-protect kb (operational waste) or under-protect tx memory (security hole). The two tables are parallel in shape but different in scoping discipline — documented in this brief's Implementation Notes.

**Chunking strategy** is the one non-trivial design decision in this brief. The choices are:
- **Fixed-size sliding window** (e.g., 500 tokens, 50-token overlap): simple, robust, language-agnostic.
- **Semantic chunking** (split on heading boundaries, keep paragraphs intact): more meaningful chunks, more complex.
- **Hybrid**: split on markdown headings (`##`) into sections, then if a section exceeds 800 tokens, fall back to fixed-window within that section.

V1 picks the **hybrid**. Reasoning: product docs are written by humans with semantic structure (headings, sections). Splitting on `##` preserves that structure when sections are reasonably sized; the fixed-window fallback handles long FAQ pages without producing 5KB chunks that dilute embeddings. The boundary at 800 tokens is heuristic — Gemini's effective context for `task_type=RETRIEVAL_DOCUMENT` is best around 200-1000 tokens per chunk; 800 leaves headroom. Documented in AC-04.

---

## Architecture pointers

- `architecture-decisions.md` §"Vector store" (line 391, the parallel kb_embeddings table), §"AI Assistant" sub-domain catalog (memory: "transaction embeddings + RAG over docs"), §"Three regimes" (Regime C for kb_embeddings — append-only; updates via re-ingest, not UPDATE).
- **Layer:** application (use case + ingestion CLI + chunker) + domain (`KbChunk` value object, ports) + infra (SQLAlchemy repo + Alembic migration + CLI entry).
- **Packages touched:**
  - `ai/memory/domain/kb_chunk.py` (`KbChunk{id, source_path, chunk_index, content, embedding, metadata, embedding_model, created_at}` — read-side projection, append-only)
  - `ai/memory/domain/value_objects/kb_metadata.py` (`KbMetadata{title, heading_path, source_revision_hash}` — JSONB shape; `heading_path` is the breadcrumb like `["Withdrawals", "Cold-tier approval"]`)
  - `ai/memory/domain/ports.py` (extends with `KbEmbeddingRepository`, `KbRetriever`, `MarkdownChunker`)
  - `ai/memory/application/use_cases/search_kb.py` (the retrieval use case wrapping the repo)
  - `ai/memory/application/use_cases/ingest_kb_directory.py` (the ingestion driver — walks directory, calls chunker, embeds, persists)
  - `ai/memory/application/markdown_chunker.py` (the hybrid chunker — pure-Python, no external NLP deps)
  - `ai/memory/infra/sqlalchemy_kb_embedding_repo.py`
  - `ai/memory/infra/migrations/006_kb_embeddings.py` (Alembic; revision after `005_tx_memory_embeddings`)
  - `ai/memory/infra/cli.py` (Click-based: `vaultchain kb ingest <path>`, `vaultchain kb list`, `vaultchain kb search <query>`)
  - `ai/memory/infra/composition.py` (extends; registers KbRetriever)
  - `docs/product/` (six baseline Markdown files — content listed in AC-09)
- **Reads:** none from other contexts.
- **Writes:** `ai.kb_embeddings`.
- **Publishes events:** `ai.KbChunkIngested{chunk_id, source_path, chunk_index}` — no V1 subscriber, registered for V2 cache-invalidation.
- **Subscribes to events:** none.
- **New ports introduced:** `KbEmbeddingRepository`, `KbRetriever`, `MarkdownChunker`.
- **New adapters introduced:** `SqlAlchemyKbEmbeddingRepository`, `HybridMarkdownChunker`. Plus fakes in `tests/ai/fakes/`.
- **DB migrations required:** yes — `006_kb_embeddings`.
- **OpenAPI surface change:** no (CLI-only in V1; the V2 RAG-augmentation brief will surface chat behaviour change but not API schema change).

---

## Acceptance Criteria

- **AC-phase4-ai-008-01:** Given migration `006_kb_embeddings`, when applied, then table `ai.kb_embeddings(id UUID PK, source_path TEXT NOT NULL, chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0), content TEXT NOT NULL CHECK (length(content) BETWEEN 20 AND 4000), embedding VECTOR(768) NOT NULL, metadata JSONB NOT NULL, embedding_model TEXT NOT NULL, embedding_dim INTEGER NOT NULL CHECK (embedding_dim = 768), source_revision_hash TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (source_path, chunk_index))` exists with: ivfflat index `idx_kb_emb_vector USING ivfflat (embedding vector_cosine_ops) WITH (lists=50)` (smaller `lists` than `tx_memory_embeddings` because the corpus is smaller — ~500 chunks, `√500 ≈ 22`, `lists=50` is a comfortable upper-rounding), b-tree `idx_kb_source ON (source_path)` (for ingestion's "which chunks already exist for this file?" lookup). Migration is idempotent. **No FK to `identity.users` — kb is global.**

- **AC-phase4-ai-008-02:** Given the `KbEmbeddingRepository` Protocol, when defined, then it declares: `async def upsert_chunks(chunks: Sequence[KbChunk]) -> None` (idempotent — `INSERT ... ON CONFLICT (source_path, chunk_index) DO UPDATE SET content = EXCLUDED.content, embedding = EXCLUDED.embedding, metadata = EXCLUDED.metadata, source_revision_hash = EXCLUDED.source_revision_hash`); `async def delete_by_source(source_path: str) -> int` (returns count deleted; used during re-ingestion when a doc shrinks — old chunk_index values orphan otherwise); `async def search(query_vector: list[float], *, limit: int, min_similarity: float) -> list[KbSearchResult]` — returns `(chunk, similarity)` pairs filtered by `similarity >= min_similarity` (cosine similarity, computed as `1 - (embedding <=> query_vector)`); `async def list_sources() -> list[KbSourceSummary]` (per-source-path aggregates: chunk_count, latest_revision_hash, latest_created_at). The Protocol is `runtime_checkable`. **`search` does NOT take a `user_id` — global by design**, in deliberate contrast to `phase4-ai-007`'s `TxMemoryEmbeddingRepository.search` which takes user_id as non-Optional. The two repos sit side-by-side in the same package as a typed reminder of the scoping difference.

- **AC-phase4-ai-008-03:** Given the `KbRetriever` use case in `ai/memory/application/use_cases/search_kb.py`, when invoked via `await retriever.search(query_text, *, limit=5, min_similarity=0.65)`, then it: (1) validates `1 <= limit <= 20` (raises `ValueError` outside); (2) validates `0.0 <= min_similarity <= 1.0`; (3) calls `EmbeddingsClient.embed_one(query_text, task_type=TaskType.RETRIEVAL_QUERY)` — task_type matches read-side per ADR-010; (4) calls `repo.search(query_vector, limit=limit, min_similarity=min_similarity)`; (5) returns the result list. On `EmbeddingsUnavailableError`, surfaces it (not silent-empty — same discipline as `phase4-ai-007` AC-03). The `min_similarity` floor (default 0.65, configurable) is the key quality knob: below ~0.6 cosine, Gemini retrieval matches are typically not useful; the LLM is better off saying "I don't know" than being shown weakly-related docs and hallucinating.

- **AC-phase4-ai-008-04:** Given the `HybridMarkdownChunker` in `ai/memory/application/markdown_chunker.py`, when invoked via `chunker.chunk(markdown_text, *, source_path)`, then: (1) parses the markdown via `mistune>=3.0` (canonical Python markdown parser, already used elsewhere in the codebase if applicable, else newly pinned — Phase 1's brief didn't pin it; this brief pins it); (2) splits into sections at `##` (H2) headings; (3) tracks `heading_path` as a stack — H1 + H2 currently in scope; for each section, the metadata heading_path captures the breadcrumb; (4) if a section's content (after H2 stripped) is ≤800 tokens (estimated as `len(content) // 4`), emits one chunk; (5) if >800 tokens, falls back to fixed-window: 600-token chunks with 100-token overlap (overlap preserves continuity for queries spanning chunk boundaries); (6) each emitted chunk is 100–4000 chars (the table's CHECK constraint); chunks below 100 chars are dropped (likely empty sections); chunks above 4000 chars are hard-split mid-paragraph (rare but defended); (7) returns `list[KbChunk]` with `chunk_index` 0-based per source_path, content, metadata (heading_path + source_path's title from H1), and a placeholder embedding (set later by ingestor).

- **AC-phase4-ai-008-05:** Given the `IngestKbDirectory` use case in `ai/memory/application/use_cases/ingest_kb_directory.py`, when invoked via `await ingestor.execute(docs_path: Path)`, then: (1) walks `docs_path` recursively, finding `.md` files; (2) for each file: reads content, computes `source_revision_hash = sha256(content)[:16]`, compares to existing chunks' `source_revision_hash` via `repo.list_sources()` — if unchanged, skip (idempotent on no-change); (3) for changed/new files: chunks via `MarkdownChunker.chunk`, batches embeddings via `EmbeddingsClient.embed_batch(texts, task_type=TaskType.RETRIEVAL_DOCUMENT)` (max 100 per batch — adapter chunks larger), populates each chunk's embedding, updates metadata's `source_revision_hash`; (4) calls `repo.delete_by_source(source_path)` to remove old chunk_indexes BEFORE upserting (handles the case where a doc edit reduces chunk count); (5) calls `repo.upsert_chunks(chunks)` in a single UoW per file; (6) emits `ai.KbChunkIngested` per chunk via outbox; (7) returns `IngestSummary{files_processed, files_skipped, chunks_inserted, chunks_updated, chunks_deleted}`. Ingestion is **append-only-ish at the row level** (rows can be deleted only via `delete_by_source` for re-ingestion; no other UPDATE/DELETE paths exist); upsert semantically is a delete-then-insert per source, matching Regime C discipline.

- **AC-phase4-ai-008-06:** Given the CLI in `ai/memory/infra/cli.py`, when invoked: `vaultchain kb ingest docs/product/` runs `IngestKbDirectory` and prints the summary; `vaultchain kb list` prints `repo.list_sources()` as a table; `vaultchain kb search "how do I withdraw"` runs `KbRetriever.search` with default limit/threshold and prints `(similarity, source_path, heading_path, content[:200])` per result. The CLI is wired via Click (`>=8.1`); entry point in `pyproject.toml`'s `[project.scripts]` table. Errors propagate to non-zero exit codes; `--verbose` flag enables structlog DEBUG output.

- **AC-phase4-ai-008-07:** Given the source-revision-hash short-circuit in AC-05 step 2, when the same `vaultchain kb ingest docs/product/` is run twice on unchanged content, then: (1) first run inserts N chunks across M files; (2) second run reads each file, computes hash, compares to stored — skips all M files; (3) second run emits zero `KbChunkIngested` events; (4) IngestSummary reports `files_skipped=M, chunks_inserted=0, chunks_updated=0, chunks_deleted=0`. The hash is per-file, not per-chunk, which is the right granularity: any edit to a file re-ingests its chunks.

- **AC-phase4-ai-008-08:** Given a doc edit that changes content (different hash), when re-ingested, then: (1) old chunks for that source_path are deleted via `delete_by_source`; (2) new chunks are upserted with current embeddings; (3) other source_paths are untouched; (4) chunk IDs change (new UUIDs) — V2 considerations like "stable chunk IDs across edits" are explicit non-goals here. Tested via testcontainers-Postgres adapter test.

- **AC-phase4-ai-008-09:** Given the `docs/product/` baseline corpus, when committed, then six Markdown files exist: `getting-started.md` (intro, account creation, KYC overview), `kyc-tiers.md` (tier_0/tier_1/tier_2 limits, rejection handling), `withdrawals.md` (send flow, fee model, threshold approval, cold tier explanation), `deposits.md` (per-chain receive flow, confirmation depths, deposit limits), `security.md` (TOTP, session management, "we never ask for your seed phrase"), `troubleshooting.md` (FAQ — "my withdrawal is pending too long", "why does my deposit show 'awaiting confirmations'", "how to contact support"). Each file is 500–3000 words, well-structured with `##` H2 headings. The PR includes one ingestion run on these files and the resulting chunk count is recorded in the PR description (~50–100 chunks expected). These are the V1 RAG corpus; V2 will expand.

- **AC-phase4-ai-008-10:** Given the ivfflat parameters from AC-01 (`lists=50, probes=10`), when the system has all six baseline docs ingested (~50–100 chunks), then: (1) `repo.search(vector, limit=5, min_similarity=0.65)` returns top-5 results in <30ms p95 (smaller corpus than tx_memory; faster p95 expected); (2) recall vs exact-knn baseline is ≥98% on the small corpus (small lists, high probes ratio means near-exact recall). A benchmark test in `tests/ai/memory/infra/test_kb_ivfflat_recall.py` verifies. **Why these parameters:** with N≈100 rows, the corpus is small enough that `lists=50` over-shards slightly but pays for itself when the corpus grows toward V2's expected ~1000 chunks; `probes=10` over-scans (per-query touches ~20% of lists) which is acceptable at small scale. The migration documents the rationale inline.

- **AC-phase4-ai-008-11:** Given the `min_similarity` floor parameter, when the query vector is far from all stored chunks (cosine similarity < 0.65 for all), then `KbRetriever.search` returns an empty list — NOT an error. The caller (V2 chat-augmentation brief) interprets empty as "I have no relevant docs; the LLM should answer from its general knowledge or say it doesn't know." Tested via a query like "how do I bake bread" against a wallet-product corpus.

- **AC-phase4-ai-008-12:** Given the import-linter contract from `phase4-ai-007` AC-11 ("ai.memory raw SQL banned in application"), when this brief introduces `IngestKbDirectory`, `SearchKb`, etc. in `ai/memory/application/`, then the contract still passes — none of the new application files import `sqlalchemy`. The CLI in `ai/memory/infra/cli.py` is allowed to import sqlalchemy via the repo. **The contract continues to be the structural enforcement** of the no-raw-SQL-in-application rule across both `tx_memory` and `kb` halves of the memory sub-domain. Tested by running `lint-imports` and asserting pass.

---

## Out of Scope

- Chat-context injection (V2 prompt-augmentation brief).
- Admin UI for managing kb chunks (V2).
- Multi-language / translated docs (V2).
- Document versioning history (V2).
- Real-time doc reload / file-watcher (V2).
- A dedicated "search_docs" tool for the LLM to invoke (V2 surface).
- Per-doc access controls (V2 — V1 docs are global product info).
- Cross-user-leak property test (not applicable — kb is global by design).
- Re-embedding migration on model change (V2; same backlog item as `phase4-ai-007`).
- Encryption-at-rest of `content` (V2; product docs are public anyway).

---

## Dependencies

- **Code dependencies:** `phase4-ai-001` (EmbeddingsClient, ADR-010); `phase4-ai-007` (parallel patterns: ivfflat tuning, `SET LOCAL ivfflat.probes` discipline, repo Protocol layout); `phase1-shared-003` (UoW); `phase1-shared-004` (outbox for `ai.KbChunkIngested` event).
- **Data dependencies:** migrations 001–005 applied.
- **External dependencies:** `mistune>=3.0` (markdown parser; new pin if not already present), `click>=8.1` (CLI; if Phase 1 already has it, no new pin), `pgvector>=0.3` (already pinned by `phase4-ai-001`).
- **Configuration:** new env var `KB_DEFAULT_MIN_SIMILARITY` (default `0.65`), `KB_DEFAULT_LIMIT` (default `5`).

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/ai/memory/domain/test_kb_chunk.py` — construction, content length validation (20–4000), embedding dim validation (= 768), JSONB metadata round-trip.
- [ ] **Domain unit tests:** `tests/ai/memory/domain/test_kb_metadata.py` — construction, JSONB serialisation, heading_path stack semantics.
- [ ] **Application tests:** `tests/ai/memory/application/test_search_kb.py` — happy path, limit/min_similarity validation, empty result on threshold violation, EmbeddingsUnavailableError surfaces. Covers AC-03, AC-11.
- [ ] **Chunker tests:** `tests/ai/memory/application/test_markdown_chunker.py` — section-per-H2 case (small section → 1 chunk), large-section fallback to fixed-window (>800 tokens), heading_path tracking through nested headings, edge cases (empty sections dropped, very long content hard-split). Covers AC-04.
- [ ] **Application tests:** `tests/ai/memory/application/test_ingest_kb_directory.py` — happy path on synthetic 3-file corpus, hash-skip on unchanged files (covers AC-07), delete-then-upsert on changed file (covers AC-08), batch embedding called with task_type=RETRIEVAL_DOCUMENT, IngestSummary shape.
- [ ] **CLI tests:** `tests/ai/memory/infra/test_cli.py` — `kb ingest` happy path, `kb list` output format, `kb search` returns formatted results, `--verbose` flag enables debug log. Covers AC-06.
- [ ] **Adapter tests (testcontainers):** `tests/ai/memory/infra/test_sqlalchemy_kb_repo.py` — upsert idempotency on `(source_path, chunk_index)` unique, `delete_by_source` count, `search` cosine ordering + similarity floor, `list_sources` aggregates, EXPLAIN shows ivfflat usage.
- [ ] **Adapter benchmarks:** `tests/ai/memory/infra/test_kb_ivfflat_recall.py` — synthetic 100-chunk corpus, recall ≥98% vs exact knn, p95 latency <30ms. Covers AC-10.
- [ ] **Migration tests:** `tests/ai/memory/infra/test_migration_006_kb_embeddings.py` — apply + rollback, idempotency, dim CHECK enforced, ivfflat index present. Covers AC-01.
- [ ] **Integration test (real corpus):** `tests/ai/memory/test_baseline_corpus_ingest.py` — runs ingestion on `docs/product/`, asserts ≥30 chunks total, asserts a known query like `"how to verify my account"` returns chunks from `kyc-tiers.md` or `getting-started.md`. Covers AC-09 + lite end-to-end.
- [ ] **Architecture tests:** existing `tests/architecture/test_memory_imports.py` from `phase4-ai-007` extended to cover kb files. Covers AC-12.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All listed test categories implemented and passing locally.
- [ ] `import-linter` contracts pass — including the existing "ai.memory raw SQL banned in application" extended to cover both halves.
- [ ] `mypy --strict` passes for `vaultchain.ai.memory.*` and `vaultchain.cli.*` (CLI module).
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass (`ai/memory/application/` ≥ 90%, `ai/memory/infra/` ≥ 85%).
- [ ] OpenAPI schema unchanged.
- [ ] Three new ports declared (`KbEmbeddingRepository`, `KbRetriever`, `MarkdownChunker`) with fakes.
- [ ] One new Alembic revision (`006_kb_embeddings`) committed + applied + rolled-back tested.
- [ ] One new domain event (`ai.KbChunkIngested`) registered.
- [ ] Six baseline product-doc Markdown files committed under `docs/product/`.
- [ ] CLI entry `vaultchain kb ingest|list|search` wired via `[project.scripts]` in `pyproject.toml`.
- [ ] `pyproject.toml`: `mistune>=3.0` pinned. (`click` likely already present; verify.)
- [ ] `docs/runbook.md` updated with: how to ingest after editing docs (`vaultchain kb ingest docs/product/`), how to inspect a stuck or stale corpus (`vaultchain kb list`), the meaning of `min_similarity` and when to tune it.
- [ ] Single PR. Conventional commit: `feat(ai/memory): kb_embeddings + RAG retrieval port + ingestion CLI [phase4-ai-008]`.
- [ ] PR description: a sequence diagram of one ingestion run (CLI → directory walk → per-file hash check → chunker → batch embed → upsert) plus a small diagram showing `ai.tx_memory_embeddings` and `ai.kb_embeddings` side-by-side highlighting the user-scoping difference.

---

## Implementation Notes

- **Why hybrid chunking, not fixed-window only:** product docs from a portfolio project are written by humans for humans — they have semantic structure. Fixed-window only would chop "Cold-tier explanation" into "Cold-tier expla" + "nation: when the policy" with predictable embedding-quality consequences. The hybrid keeps the common case clean and falls back gracefully on the rare long section. Documented in the chunker module docstring with a one-paragraph rationale that a reviewer reading the file will encounter immediately.
- **Why `mistune` not `markdown-it-py` or `markdown` (PyPI):** `mistune` is the most production-deployed pure-Python markdown parser, AST-shaped output is convenient for chunking, fast (C-extension optional). The choice is reversible — swap is a one-class adapter change. Documented as "not architectural; just the implementation".
- **The `source_revision_hash` field has two roles**: ingestion-time skip (AC-07) AND audit ("when did this chunk get re-embedded?"). Computed once per file, copied into every chunk's metadata.
- **`delete_by_source` before `upsert_chunks`** (AC-05 step 4): the order matters when a doc shrinks (10 chunks → 6 chunks). Without delete-first, chunk_indexes 6..9 would orphan with stale content + stale embeddings. The delete-then-upsert is atomic within a UoW.
- **CLI is intentionally minimal.** No `--watch` mode, no JSON output, no piping helpers. V1 is "edit doc, run ingest, commit". V2 can build niceties.
- **`task_type=RETRIEVAL_DOCUMENT` on ingestion, `RETRIEVAL_QUERY` on search.** Per ADR-010 / `phase4-ai-001` AC-07. This is the specific Gemini-quality path; the test verifies both calls use the right task_type.
- **No FK from `kb_embeddings` to anything**: deliberately. The corpus is independent of users, transactions, anything. Cleanest model.
- **The two memory tables are deliberately parallel in shape** (id, content/summary, embedding, metadata, embedding_model, embedding_dim, created_at) — making the architectural difference visible at a glance: one has user_id and tx_id FK, the other doesn't. The Implementation Notes call this out so a reviewer scanning both migration files sees the contrast.
- **Ingestion rate-limits.** With the default 100-batch in EmbeddingsClient (from `phase4-ai-001` AC-07), a corpus of 100 chunks → 1 batch call → ~1 second. No need for explicit rate-limiting; document the implicit budget.

---

## Risk / Friction

- **Chunking strategy is judgement-call territory.** A reviewer might prefer pure-fixed-window for "boring is good"; another might want fancier semantic chunking with sentence boundaries. The hybrid is defensible middle ground, documented; if Tier-3 evals (`phase4-evals-001`) show poor RAG quality, V2 revisits.
- **No cross-user-leak test for kb is the right call but optically unusual.** Out of Scope explicitly notes this. The Implementation Notes contrast with `phase4-ai-007`. A reviewer comparing the two repos sees the deliberate asymmetry: tx memory has user_id everywhere; kb has none. This *is* the test.
- **Static corpus risks staleness.** A user reads a doc, asks the AI a question, gets an answer based on a STILL-EARLIER version of the doc. Mitigation: `source_revision_hash` makes the staleness measurable; a future "doc audit" tool could surface chunks whose hash doesn't match current file. V1 acceptable: the corpus is small and authored by the project owner.
- **`min_similarity=0.65` floor is empirical.** If product docs are well-aligned with realistic queries, this works. If queries drift (slang, indirect phrasings), the floor cuts off useful results. Tier-3 evals are where this gets calibrated. Documented as a knob.
- **ivfflat over a 50-chunk corpus is overkill.** A flat scan would be ~5ms. The index pays off at ~500+ chunks. V1 keeps the index for forward-compat (V2 corpus growth) and to keep the two tables architecturally identical. Acceptable overhead.
- **The CLI is not currently tested for concurrent invocations.** If two engineers run `vaultchain kb ingest` simultaneously on the same files, the upsert pattern is correct (last-writer-wins per `(source_path, chunk_index)`) but the embedding API budget gets double-spent. Documented as "don't do that"; not a structural problem.
- **Document quality is not enforced.** A 3-line doc with no headings still gets ingested. Chunker's "drop chunks <100 chars" is the only floor. A future doc-lint pre-commit hook could enforce structure; out of V1 scope.
