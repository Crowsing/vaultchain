---
ac_count: 7
blocks:
- phase4-demo-001
complexity: S
context: ai
depends_on:
- phase4-ai-005
- phase4-ai-006
- phase4-ai-008
- phase4-ai-009
- phase4-web-008
estimated_hours: 4
id: phase4-evals-001
phase: 4
sdd_mode: strict
state: ready
title: Tier-3 live evals harness (manual, not CI gate)
touches_adrs:
- ADR-006
---

# Brief: phase4-evals-001 — Tier-3 live evals harness (manual, not CI gate)


## Context

`architecture-decisions.md` §"AI testing — three tiers" (line 564) and ADR-006 codify three levels of AI testing:

- **Tier 1 — unit tests on tool executors.** Covered by `phase4-ai-003`, `phase4-ai-004`, `phase4-ai-005`, etc.
- **Tier 2 — SSE protocol tests with recorded conversation traces.** Covered by `phase4-ai-006` AC-10 (six baseline fixtures committed).
- **Tier 3 — live evals run manually, not CI gate.**

This brief delivers Tier 3. The architecture is explicit that Tier 3 is **manual** and **not a CI gate** — for cost reasons (live Anthropic API calls × dozens of test cases × every CI run = unaffordable) and for behavioural-stability reasons (Anthropic model updates can shift outputs without breaking the protocol; you want a human looking at "did the assistant get noticeably worse?" rather than a binary pass/fail).

**What Tier 3 evals do:**

For each scenario in a curated suite, run the chat endpoint end-to-end against real Anthropic, capture the resulting conversation, and grade it against scenario-specific assertions: tool selection correctness, response factual accuracy (against ground-truth seeded data), refusal patterns (off-domain queries handled gracefully), language handling, prepared-action correctness, RAG citation quality. Output is a single CSV/JSON report with per-scenario verdict (`pass | warn | fail`) and a one-paragraph commentary, plus aggregate metrics.

**The eval suite is a portfolio artefact.** The CSV/JSON output, captured at every Anthropic model upgrade and every system-prompt change, IS the proof-of-quality the project demonstrates. A reviewer looking at the repo sees `evals/reports/2026-04-25-claude-sonnet-4.json` and similar files — material evidence that the AI assistant is grounded, consistent, and production-quality.

**Twelve V1 scenarios** (the suite expands in V2):

1. **balance_check_simple** — "What's my balance?" → assistant calls `get_balances`, summarises numbers correctly.
2. **balance_check_specific_chain** — "How much SOL do I have?" → narrowed answer, no chain-mismatch confusion.
3. **history_recent** — "Show me my last 5 transactions." → `get_recent_transactions`, summary with hashes.
4. **history_filtered** — "Did I send anything to 0x456 last week?" → tool with filter, accurate summary or "I don't see any."
5. **kyc_status_tier_0** — for a tier_0 user: "Why can't I send more than $1000?" → `get_kyc_status`, explains tier limits, mentions upgrade path.
6. **kyc_status_rejected** — for a tier_0_rejected user: same question → handles compassionately, points to support channels.
7. **prepare_send_happy** — "Send 0.1 ETH to 0xabc..." → `prepare_send_transaction`, prep card preview accurate, threshold policy decision correct.
8. **prepare_send_route_to_admin** — for a high-value user with high-value send: "Send $5000 USDC to 0x...". → prep card has `requires_admin=true` badge.
9. **prepare_send_invalid_address** — "Send 1 ETH to badaddress" → assistant catches via tool's address-validation error and reports clearly without trying retry-loops.
10. **off_domain_refusal** — "What's the weather today?" → graceful off-domain refusal, redirects to wallet topics.
11. **multilingual_ukrainian** — "Який мій баланс ETH?" → handles in Ukrainian, returns numbers, language style natural.
12. **rag_grounded_answer (V2-bridge)** — "How does the cold-tier approval work?" → uses kb retrieval (or general knowledge), answer matches `docs/product/withdrawals.md` content. Tagged "V2-bridge" because the chat-context RAG injection is V2 per `phase4-ai-008` Out-of-Scope; in V1 this scenario verifies the LLM's general knowledge gives a reasonable answer (so V2 RAG augmentation is improvement, not rescue).

The grading is **manual + heuristic**: an automated grader compares against rubric thresholds (tool was/wasn't called, response contains expected keywords, no banned-phrase like "I don't have access" when tools should have given it access), and a human reviewer skims the captured conversations to flag subjective issues. The architecture is explicit: this is not regex-matching for ground truth; this is "did the assistant behave the way a knowledgeable user would expect."

---

## Architecture pointers

- `architecture-decisions.md` §"AI testing — three tiers" (the ADR-006 description), §"AI Assistant" (the sub-domains being evaluated).
- **Layer:** test infrastructure + scenarios + grader + report generator. NOT in the production package tree.
- **Packages touched:**
  - `evals/` (new top-level directory — peer to `tests/`, `web/`, etc.)
    - `evals/__init__.py`
    - `evals/runner.py` (the orchestrator: takes a scenario, opens a real chat session, captures the full event stream + final state, grades, returns a `ScenarioReport`)
    - `evals/scenarios/` (one Python file per scenario; each declares `input_text`, `seed_state`, `expected_tools`, `expected_keywords`, `banned_keywords`, `grader: Callable[[ScenarioRun], Verdict]`)
    - `evals/scenarios/balance_check_simple.py` … one file per scenario above
    - `evals/grader.py` (heuristic graders — `tool_was_called`, `response_contains_any`, `response_contains_none_of`, `policy_decision_matches`)
    - `evals/seeds.py` (deterministic test-user fixtures — three users with various states: fresh tier_0, mid tier_1, tier_0_rejected)
    - `evals/report.py` (renders `ScenarioReport` list to JSON + CSV + Markdown summary)
    - `evals/cli.py` (Click: `vaultchain evals run [--scenarios=...]`, `vaultchain evals report <report.json>`)
  - `evals/reports/` (committed historical reports, one per significant evaluation run — model upgrade, prompt change)
- **API consumed:** the live `POST /api/v1/ai/chat` endpoint (against staging or local-with-real-Anthropic).
- **OpenAPI surface change:** no.
- **Storage:** evals run against a dedicated test database (testcontainers or a clean staging DB); seed data via `evals/seeds.py`.

---

## Acceptance Criteria

- **AC-phase4-evals-001-01:** Given the directory `evals/` is created peer-to-`tests/`, when `python -c "import evals"` is run, then it imports cleanly. The directory is excluded from production code coverage and from `pyright`/`mypy --strict` defaults (it has its own looser `mypy.ini` profile because eval code is exploratory). Linter rules pass with the looser profile.

- **AC-phase4-evals-001-02:** Given the `Scenario` dataclass in `evals/scenarios/_base.py`, when defined, then it has fields: `name: str` (matches filename); `input_text: str` (the user message to send); `seed_state: SeedState` (which test user fixture, what initial DB state — e.g., "user_tier_0_with_5_eth"); `expected_tools: set[str]` (tool names that SHOULD be called — empty for off-domain); `expected_keywords: Sequence[str]` (response text should contain at least one); `banned_keywords: Sequence[str]` (response should contain none — e.g., banned: `["I don't have access", "I cannot determine"]` for scenarios where tools SHOULD give access); `expected_prepared_action: PrepActionExpectations | None` (optional structured expectation for prep_send scenarios — e.g., `{kind: 'send_transaction', requires_admin: True, amount_human: '5000', asset: 'USDC'}`); `grader: Callable[[ScenarioRun], Verdict]` (custom grader if needed; defaults to a standard composite grader from `evals/grader.py`).

- **AC-phase4-evals-001-03:** Given the eval `runner.py`, when invoked via `python -m evals.cli run --scenarios=balance_check_simple`, then: (1) starts the test backend (or assumes staging is reachable); (2) seeds the database via `evals/seeds.py` per scenario's `seed_state`; (3) authenticates as the seeded test user; (4) opens an SSE chat session with `input_text`; (5) drains all events, captures the final assistant message + tool_use events + prepared_actions emitted; (6) runs the scenario's grader; (7) returns a `ScenarioReport{name, verdict: 'pass'|'warn'|'fail', score: 0.0..1.0, notes: list[str], duration_ms, model: str, captured_events: list[dict], captured_messages: list[dict]}`. Each scenario takes ~5–30 seconds against real Anthropic — total suite (12 scenarios) ~5 minutes.

- **AC-phase4-evals-001-04:** Given the standard composite grader, when invoked, then it scores: (a) tool selection (1.0 if `expected_tools == actually_called_tools`, 0.5 if subset matches, 0.0 if disjoint) — weight 30%; (b) keyword presence (1.0 if any `expected_keywords` matched, 0.0 otherwise) — weight 25%; (c) banned-keyword absence (1.0 if no `banned_keywords` matched, 0.0 if any) — weight 20%; (d) prepared-action match (1.0 if `expected_prepared_action` matches the captured prep card structurally, 0.0 if mismatch, N/A skipped) — weight 25%; total `score ∈ [0, 1]`. Verdict thresholds: `score >= 0.8 → pass, 0.6 <= score < 0.8 → warn, score < 0.6 → fail`. Notes string: per-component breakdown for the report.

- **AC-phase4-evals-001-05:** Given the seeded test users in `evals/seeds.py`, when used, then three deterministic fixtures exist: `seed_user_fresh_tier_0` (tier_0, no applicant_started, 1 wallet on Sepolia with 0.5 ETH and 100 USDC), `seed_user_active_tier_1` (tier_1, 3 wallets across chains, ~10 historical transactions of mixed status), `seed_user_rejected` (tier_0_rejected with reject_labels including 'DOCUMENT_DAMAGED'). Each is reproducible: same seed → same row data. The seeds are SQL-shaped (raw INSERT statements) for clarity and version control.

- **AC-phase4-evals-001-06:** Given the report renderer in `evals/report.py`, when called with a `list[ScenarioReport]`, then it produces three artefacts: (a) `report.json` — full structured data, the canonical record; (b) `report.csv` — one row per scenario, columns `name, verdict, score, duration_ms, model, summary_note`; (c) `report.md` — human-readable summary with aggregate stats (pass/warn/fail counts, per-scenario one-line verdict + score), pasted at the top of any documentation that wants to cite eval state. Reports are timestamped: `evals/reports/<YYYY-MM-DD-HH-MM>-<model_short>/` directory.

- **AC-phase4-evals-001-07:** Given a recorded run captured via `runner.py`, when stored in the report's `captured_events` field, then the events are the same shape as `phase4-ai-006`'s `FrontendEvent` JSON serialisation — bytes-equivalent to what the frontend would have received. This makes the captured-events log re-playable: a future test can stub the LLM with these events to reproduce the conversation deterministically (Tier-2 fixtures are essentially graduated Tier-3 captures). Documented as the path "promote a Tier-3 run to a Tier-2 fixture": copy the events into `tests/ai/conversations/fixtures/`, write the expected trace, commit.

- **AC-phase4-evals-001-08:** Given the CLI in `evals/cli.py`, when invoked: `vaultchain evals run` runs the full suite; `vaultchain evals run --scenarios=balance_check_simple,off_domain_refusal` runs subset; `--against=staging` (default) targets staging; `--against=local` runs against `http://localhost:8000` with a local server that the developer has already started; `--model=<override>` overrides the chat model (e.g., for cross-model comparison); `--output-dir=<path>` overrides the default `evals/reports/<timestamp>/`; `--no-real-anthropic` short-circuits to a fake LLM (useful for grader development without burning quota — produces a `report.json` with `model: "fake"` so it's never confused with a real run). Errors to non-zero exit codes; `--verbose` enables debug logging.

- **AC-phase4-evals-001-09:** Given the documentation in `evals/README.md`, when a future developer reads it, then it explains: (1) what Tier-3 evals are and why they're not in CI; (2) when to run them (model upgrade, system-prompt change, before a release); (3) how to interpret a report (the verdict thresholds, what "warn" means); (4) how to add a new scenario (copy a template file, fill in fields, run); (5) how to promote a Tier-3 capture to a Tier-2 fixture. The README is the entry point — a new contributor lands here, not in the runner code.

- **AC-phase4-evals-001-10:** Given a baseline eval run committed at PR merge time, when the report is examined, then: (a) the report is in `evals/reports/<timestamp>-baseline/`; (b) at least 10 of the 12 scenarios verdict `pass`; (c) any `warn` or `fail` scenarios have manual commentary in the README explaining why and the planned remediation. This is the "first run" — a portfolio artefact + a measurable starting line for V2 improvements. **The two scenarios most likely to warn-or-fail in V1**: `multilingual_ukrainian` (Sonnet's Ukrainian quality is good but not perfect; expected to occasionally produce slightly stilted phrasing) and `rag_grounded_answer` (V2-bridge — V1 has no chat-context RAG, so the answer relies on Sonnet's general knowledge; documented as expected gap).

---

## Out of Scope

- CI integration. Tier 3 is manual by ADR-006 design.
- Cross-model benchmarking (Sonnet vs Opus vs Haiku) — V2; the `--model` flag enables it but a curated benchmark is its own brief.
- Adversarial / red-team scenarios (jailbreak attempts, prompt injection): V2 — a separate `evals/adversarial/` directory with restricted access.
- Human-rater integration (Mechanical Turk-style scoring): V2 — V1 grader is heuristic + manual review.
- Performance benchmarking (latency p50/p95): V2 — out of scope here, would belong in a load-test brief.
- A/B testing of system-prompt variants: V2.
- Eval-driven prompt optimization (auto-tuning): V2 / experimental.
- Coverage of `phase4-ai-009` suggestions evaluation: V2; suggestions rule logic is deterministic and covered by Tier-1 unit tests; no value in Tier-3 for them.

---

## Dependencies

- **Code dependencies:** `phase4-ai-006` (chat endpoint), `phase4-ai-002` through `phase4-ai-005` (the ports + tools + prep flow being evaluated).
- **Data dependencies:** access to a staging DB (or local with full Phase 4 stack); ability to seed test users.
- **External dependencies:** `httpx>=0.27` for the SSE client (already pinned); `click>=8.1` (CLI; already pinned by `phase4-ai-008`); access to live Anthropic API key for runs (developer's `ANTHROPIC_API_KEY` env var).

---

## Test Coverage Required

- [ ] **Grader unit tests:** `evals/test_grader.py` — each grading function (tool_match, keyword_presence, banned-keyword, prep-action match, composite score) tested with hand-crafted inputs. Covers AC-04.
- [ ] **Report renderer tests:** `evals/test_report.py` — JSON / CSV / Markdown produce expected shapes. Covers AC-06.
- [ ] **Seed fixtures tests:** `evals/test_seeds.py` — applying each seed produces the expected DB state (testcontainers Postgres). Covers AC-05.
- [ ] **CLI smoke tests:** `evals/test_cli.py` — `--no-real-anthropic` flag runs against fake LLM, produces a report; flag combinations work. Covers AC-08.
- [ ] **Scenario smoke (no real Anthropic):** `evals/test_scenarios_smoke.py` — each of the 12 scenarios loads, has valid Schema (name matches filename, expected_tools is a set, etc.). Doesn't run against Anthropic; just validates scenario file structure.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All listed test categories implemented and passing locally.
- [ ] 12 scenario files committed in `evals/scenarios/`.
- [ ] CLI `vaultchain evals` registered via `[project.scripts]` (or runs via `python -m evals.cli`).
- [ ] One baseline run committed in `evals/reports/<timestamp>-baseline/` against the latest released chat model — covers AC-10.
- [ ] `evals/README.md` documents the workflow per AC-09.
- [ ] `mypy` passes with the looser `evals/mypy.ini` profile.
- [ ] `ruff check` and `ruff format` clean.
- [ ] No production code changes — `evals/` is purely additive.
- [ ] Single PR. Conventional commit: `feat(evals): Tier-3 live eval harness + 12 scenarios + baseline report [phase4-evals-001]`.
- [ ] PR description: a screenshot of the baseline `report.md` (the Markdown summary), ideally showing pass/warn/fail counts. This lets a reviewer grok eval state at a glance.

---

## Implementation Notes

- **The runner authenticates as a seeded user via the magic-link bypass** that `phase1-identity-002` provides for testing (or whatever the project's test-auth mechanism is). Don't re-auth for each scenario — share the session per seed.
- **Scenarios are Python files, not YAML**, because the `grader: Callable` is most naturally code. YAML scenarios with a "grader_name" string referencing a registry would work but adds indirection. Python is direct.
- **The runner's SSE client** parses the same wire format as `phase4-ai-006`'s frontend; reuse `@microsoft/fetch-event-source` semantics in Python via `httpx.stream` + manual block parsing (~30 lines, parallel to the frontend implementation).
- **Capturing events for replay (AC-07)** stores the raw `FrontendEvent` JSON; the same structure that `phase4-ai-006`'s SSE writer emits. This is what makes the Tier-2 promotion path clean.
- **The "baseline" run from AC-10** is committed to git so future runs can be diffed against it. A reviewer reading the repo sees the baseline and the trajectory.
- **Cost containment:** running the full suite once costs ~$0.20–0.50 in Anthropic API fees (12 scenarios × ~5k tokens average × Sonnet rates). At 2-3 runs per significant change, costs are negligible. Documented in README.
- **Don't grade response naturalness automatically.** That's reviewer-eye territory. The grader covers structural correctness (right tools called, no banned phrases); the README explicitly tells the reviewer "skim the captured assistant text in the JSON for tone, accuracy, refusal patterns."
- **The `--against=local` mode** assumes the developer has run `docker compose up` with the full stack. Document the prereqs in the README.

---

## Risk / Friction

- **Evals will sometimes flake** — Anthropic responses are not deterministic. The grader's threshold-based verdict (0.8 pass, 0.6 warn) absorbs ~10% variation. If a scenario flakes more, raise the threshold or make the rubric less strict. Document.
- **Reviewer may ask why this isn't a CI gate.** ADR-006 answers: cost + behavioural shifts that aren't bugs (Anthropic-side model improvements changing exact wording). Tier 2 (recorded conversations) IS a CI gate — that protects protocol stability. Tier 3 protects assistant quality, which is a slower-moving signal that benefits from human judgement.
- **The 12-scenario suite is small.** A V2 expansion would target 50+ scenarios across tool combinations, edge cases, and adversarial inputs. V1 baseline is intentional — proves the pattern works, leaves room.
- **`multilingual_ukrainian` and `rag_grounded_answer` expected to warn** (AC-10). Document upfront in README so the baseline-run report's two yellow rows aren't seen as failure but as known V1 boundaries. The portfolio-positive framing: "V1 baseline shows 10/12 scenarios pass; the two warns are known boundaries documented for V2 work — multilingual quality and chat-context RAG."
- **The seed users are minimal.** A future expansion would introduce realistic users with months of activity, edge-case scenarios (stuck pending tx, recently rejected KYC, large pending withdrawal). V1 covers the common surface; complex states wait for need.
- **Cost of an Anthropic outage during eval run** is just "skip the run, retry later." The runner doesn't retry on Anthropic 5xx because it would muddy the report; it logs and continues with other scenarios, marking the failed one as `model_unavailable` (a fourth verdict variant). Document.
- **Privacy of captured conversations.** Test users have synthetic data; no real PII. Documents in README that Tier-3 reports are safe to commit (no PII; only test-user data with `0xCAFE...` addresses and seed amounts).
