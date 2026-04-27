---
ac_count: 9
blocks:
- phase3-ledger-003
- phase3-admin-007
- phase3-admin-008
complexity: M
context: custody
depends_on:
- phase3-custody-003
- phase2-chains-002
- phase2-ledger-001
- phase3-chains-004
- phase3-chains-006
estimated_hours: 4
id: phase3-custody-004
phase: 3
sdd_mode: strict
state: ready
title: Hot↔cold rebalance worker
touches_adrs:
- ADR-008
---

# Brief: phase3-custody-004 — Hot↔cold rebalance worker


## Context

Hot/cold separation is meaningless if funds never move from hot to cold — the cold address would always be empty and the architecture would be theatre. The rebalance worker fixes this: a periodic arq scheduled job walks all `(user, chain)` pairs, reads the on-chain hot balance, and if it exceeds the **rebalance threshold** for that chain+asset, builds an internal hot→cold tx of `(balance - target_buffer)` and broadcasts it. Funds settle on cold; the user's "available balance" (hot) stays at the target buffer plus any recent deposits not yet rebalanced.

The thresholds are per-chain, per-asset, declared in a config table `custody.rebalance_config`:

| chain | asset | rebalance_threshold | target_buffer |
|---|---|---|---|
| ethereum | ETH | 0.5 ETH | 0.05 ETH |
| ethereum | USDC | 100 USDC | 10 USDC |
| tron | TRX | 500 TRX | 50 TRX |
| tron | USDT | 100 USDT | 10 USDT |
| solana | SOL | 5 SOL | 0.5 SOL |
| solana | USDC | 100 USDC | 10 USDC |

Trigger logic: `if hot_balance > rebalance_threshold then transfer (hot_balance - target_buffer) to cold`. The `target_buffer` ensures the user can still send small withdrawals from hot without immediately re-triggering rebalance. The thresholds chosen are testnet-realistic — high enough that demos with 0.05 ETH withdrawals don't trigger rebalance constantly; low enough that a real deposit (the kind reviewers do during exploration) does trigger and demonstrates the mechanism.

The rebalance tx flows through the same Custody+Chains plumbing as a user withdrawal. Critically:
1. **Signing uses the hot key** (rebalance is hot→cold, not cold-signing).
2. **Posting type is `internal_rebalance`** (a new posting_type added to `ledger.postings.posting_type` enum in `phase3-ledger-003`). This excludes rebalance txs from the user-facing `GET /transactions` endpoint via a filter `WHERE posting_type != 'internal_rebalance'`. Admin queries (`phase3-admin-008`) see them.
3. **No idempotency_key on the Transaction row** — but a `UNIQUE` constraint on `(user_id, chain, asset, scheduled_at_block)` prevents double-broadcast within a single rebalance cycle. Idempotency is enforced at job-scheduling time + `caused_by_event_id` UNIQUE on the resulting Ledger posting.
4. **Fees are paid by the system** — the rebalance moves user funds, so the user's hot balance shrinks. The hot wallet's fee is part of `(balance - target_buffer - estimated_fee)` to ensure the tx lands. Document the trade-off: every rebalance costs the user ~$0.10 in testnet-equivalent fees; on mainnet would be a real consideration.

The job runs **every 4 hours** by default — not too aggressive (avoids waking up the system constantly), not too lazy (a deposit at hour 0 settles to cold by hour 4 max). Configurable via env `REBALANCE_CRON`. In tests, the trigger function is invoked directly without arq scheduling.

---

## Architecture pointers

- **Layer:** application (job + use case) + infra (config repo + composition).
- **Packages touched:**
  - `custody/application/jobs/rebalance_worker.py` (the arq-scheduled entry)
  - `custody/application/use_cases/rebalance_wallet.py` (per-(user,chain,asset) logic)
  - `custody/domain/value_objects/rebalance_config.py` (RebalanceConfig VO with thresholds)
  - `custody/domain/ports.py` (extend with `RebalanceConfigRepository`)
  - `custody/infra/sqlalchemy_rebalance_config_repo.py`
  - `custody/infra/migrations/<timestamp>_rebalance_config.py` (creates `custody.rebalance_config` + seeds 6 rows)
  - Composition root registers the cron job
- **Reads:** `custody.hot_wallets`, `custody.cold_wallets`, `custody.rebalance_config`. Cross-context: `Chains.get_native_balance + get_token_balance` (via ChainGateway).
- **Writes:** Issues a Transaction-like flow via Custody.SignTransaction (hot tier) + Chains.broadcast. Publishes `custody.RebalancePerformed{tx_hash, chain, asset, amount, from_hot, to_cold}` consumed by Ledger to post `internal_rebalance`.
- **Publishes events:** `custody.RebalancePerformed` (broadcast issued), `custody.RebalanceSkipped{reason}` (no-op cycle), `custody.RebalanceFailed{error}` (signing/broadcast/revert), `custody.RebalanceSettled` (on confirmation, consumed by Ledger to post `internal_rebalance`) — all four registered in events registry.
- **Migrations:** `custody.rebalance_config` table + seed data.
- **OpenAPI:** none for users; admin endpoint `GET /admin/api/v1/custody/rebalance-config` (read-only) added in `phase3-admin-008` for visibility.

---

## Acceptance Criteria

- **AC-phase3-custody-004-01:** Given the migration runs, when applied, then `custody.rebalance_config` exists with columns `(chain TEXT, asset TEXT, rebalance_threshold NUMERIC(78,0), target_buffer NUMERIC(78,0), enabled BOOLEAN DEFAULT true, updated_at, PRIMARY KEY(chain, asset))`. Seeded with the 6 rows from the table in Context (chain-native units: e.g., ETH threshold = `500_000_000_000_000_000` wei).

- **AC-phase3-custody-004-02:** Given the `RebalanceWorker` arq scheduled job, when triggered, then it: (1) loads all `enabled=true` rows from rebalance_config; (2) for each (chain, asset) pair, queries `custody.hot_wallets` for all wallets on that chain; (3) for each wallet, calls `RebalanceWallet(user_id, chain, asset)`. Concurrency: max 5 wallets in parallel via `asyncio.gather` with semaphore; protects RPC rate limits.

- **AC-phase3-custody-004-03:** Given `RebalanceWallet(user_id, chain, asset)` is invoked, when executed, then: (1) load hot_wallet, cold_wallet for `(user_id, chain)` — if either missing, publish `RebalanceSkipped{reason='wallet_missing'}` and return; (2) load rebalance_config for `(chain, asset)`; (3) call `ChainGateway.get_native_balance(hot.address)` (or token_balance for ERC-20/SPL) — get hot's actual on-chain balance; (4) if `hot_balance <= rebalance_threshold`, publish `RebalanceSkipped{reason='under_threshold'}` and return; (5) compute `transfer_amount = hot_balance - target_buffer - estimated_fee`; (6) if `transfer_amount <= 0`, skip with `reason='fee_exceeds_excess'`; (7) build, sign (hot KMS), broadcast → tx_hash; (8) publish `RebalancePerformed{tx_hash, chain, asset, amount=transfer_amount, hot_address, cold_address}`; (9) enqueue `ChainGateway.ReceiptMonitor` to track confirmation.

- **AC-phase3-custody-004-04:** Given a rebalance tx broadcast successfully, when the receipt monitor publishes `chain.TransactionConfirmed`, then a Custody-side handler `on_rebalance_tx_confirmed` listens and **publishes** `custody.RebalanceSettled{tx_hash, ...}` — the Ledger context (in phase3-ledger-003) subscribes and posts `internal_rebalance` postings. The Custody handler does NOT post directly to Ledger (cross-context concerns stay separated).

- **AC-phase3-custody-004-05:** Given a rebalance tx fails (signing failure, broadcast failure, on-chain revert), when the failure path triggers, then `RebalanceFailed{error: <short_reason>, chain, asset, user_id}` is published. The error is logged to Sentry. **No automatic retry within the same job** — the next scheduled run (4 hours later) tries again. Documented: "rebalance is opportunistic, not transactional. If it fails, funds stay on hot. The user is unaffected (their hot+cold balance sum is unchanged from the user's perspective; rebalance only redistributes within the user's own custody surface)."

- **AC-phase3-custody-004-06:** Given the rebalance fee estimation, when computed, then it queries `Chains.estimate_fee(chain)` and reserves enough for one transfer. For ERC-20/TRC-20/SPL transfers (involving contract calls), use the chain-specific fee from `phase2-chains-002`/`phase3-chains-004`/`phase3-chains-006`. **Critical:** native (ETH/TRX/SOL) rebalance must reserve gas in native AND leave `target_buffer` in native. ERC-20/TRC-20/SPL rebalance must reserve native fee (a separate constraint — if hot's native balance is insufficient for the fee, skip with `reason='insufficient_native_for_fee'` and log a warning that monitoring should catch).

- **AC-phase3-custody-004-07:** Given the rebalance worker runs concurrently with a user-initiated withdrawal from the same hot wallet, when both attempt to use the wallet, then: each tx fetches fresh nonce (Ethereum/Tron) or fresh blockhash (Solana) at build time. **No coordination lock** — the chain layer's nonce/blockhash mechanics serialize them. If both broadcast simultaneously and one wins the nonce race, the other gets `NonceConflict` and the rebalance handler treats this as a routine `RebalanceFailed{error='nonce_conflict'}` to retry next cycle. Documented: rebalance is best-effort; user actions take priority via the natural race.

- **AC-phase3-custody-004-08:** Given the test environment, when the worker is exercised, then tests can: (a) set up multiple users with hot+cold wallets via fixture; (b) deposit on-chain via Anvil cheat (transfer from a funded test account to user's hot); (c) trigger `RebalanceWorker` manually (not via cron); (d) advance Anvil blocks; (e) assert `RebalancePerformed` events emitted, cold balance increased, `target_buffer` remains on hot. Tests use Anvil for Ethereum, vcrpy cassettes for Tron, solana-test-validator for Solana — same fixtures as chain adapters.

- **AC-phase3-custody-004-09:** Given the cron schedule, when configured, then default is `0 */4 * * *` (every 4 hours at the top of the hour). Configurable via env `REBALANCE_CRON`. Disabled in tests (`REBALANCE_ENABLED=false` env). Documented in `docs/runbook.md`. The arq scheduler entry is loaded only if `REBALANCE_ENABLED` is `true`.

- **AC-phase3-custody-004-10:** Given the on-call `RebalanceFailed` events, when the rate of failures exceeds 3 in any 4-hour window, when monitored, then a Sentry alert fires (configured via existing `phase1-shared-005` Sentry integration). Rate is computed via Sentry's built-in alert rules; no custom metrics needed. Document the alert rule in runbook.

- **AC-phase3-custody-004-11:** Given a flag in the config row `enabled=false`, when set for a specific (chain, asset), when the worker runs, then it skips that pair entirely — `RebalanceSkipped{reason='config_disabled'}`. Useful for emergency disable without code change.

---

## Out of Scope

- Cold→hot rebalance (replenishing hot from cold): never automatic. Manual admin action via `phase3-admin-006` (the admin can approve a "withdrawal" that's actually a cold→hot internal transfer). Documented.
- Per-user opt-out: V2.
- Dynamic thresholds based on user activity: V2.
- Multi-asset atomic rebalance (e.g., rebalance all assets in one tx): out of scope; single-asset transfers are simpler and cheaper to retry.
- Real-time rebalance triggered by deposits: out of scope. Rebalance is scheduled; deposits sit on hot until next cycle. UX-acceptable since hot is still the user's address.

---

## Dependencies

- **Code dependencies:** `phase3-custody-003` (cold wallets must exist to rebalance into), `phase2-chains-002` (Ethereum write path), `phase3-chains-004` (Tron), `phase3-chains-006` (Solana), `phase2-ledger-001` (posting infrastructure).
- **Data dependencies:** `custody.cold_wallets` populated via `custody-003`'s backfill before the worker runs.
- **External dependencies:** none new.

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/custody/domain/test_rebalance_config.py` — VO equality, threshold semantics.
- [ ] **Application tests:** `tests/custody/application/test_rebalance_wallet.py` — happy path (deposit → rebalance triggers → tx broadcast), under-threshold (skips), wallet-missing (skips), insufficient-native-for-fee (skips), config-disabled (skips), nonce-conflict (failure event). Uses Fakes for Chains, Custody.SignTransaction. Covers AC-03, AC-05, AC-06, AC-07, AC-11.
- [ ] **Application tests:** `tests/custody/application/test_rebalance_worker.py` — orchestrator iterates configs and wallets, parallelism cap honored. Covers AC-02.
- [ ] **Application tests:** `tests/custody/application/test_on_rebalance_tx_confirmed.py` — handler publishes `RebalanceSettled` on confirmation. Covers AC-04.
- [ ] **Adapter tests:** `tests/custody/infra/test_sqlalchemy_rebalance_config_repo.py` — testcontainer Postgres, asserts seed data, asserts updated_at on UPDATE.
- [ ] **Adapter tests / integration:** `tests/custody/integration/test_rebalance_e2e_ethereum.py` — Anvil fixture, full e2e: deposit ETH to hot via cheat → trigger worker → tx broadcasts → mine confirmations → `RebalanceSettled` published → asserts hot balance reduced + cold balance increased. Similar tests for Tron (vcrpy) and Solana (test-validator). Covers AC-08.
- [ ] **Contract tests:** none (no public API in this brief; admin read-only is in admin-008).
- [ ] **E2E:** none.

---

## Done Definition

- [ ] All ACs verified by named test cases.
- [ ] `import-linter` contracts pass.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass.
- [ ] Three new domain events registered (RebalancePerformed, RebalanceSkipped, RebalanceFailed) plus RebalanceSettled.
- [ ] One new port (`RebalanceConfigRepository`) declared with fake.
- [ ] Cron registered with `REBALANCE_ENABLED=false` by default in dev/test.
- [ ] `docs/runbook.md` updated with: rebalance schedule, how to disable in emergencies (set config `enabled=false` or env `REBALANCE_ENABLED=false`), how to trigger manually for one wallet (CLI: `python -m custody.cli rebalance-wallet <user_id> <chain> <asset>`).
- [ ] Single PR. Conventional commit: `feat(custody): hot-cold rebalance worker [phase3-custody-004]`.
- [ ] PR description: a sequence diagram of one rebalance cycle (config load → balance check → build → sign → broadcast → monitor → ledger post).

---

## Implementation Notes

- The `RebalanceWallet` use case shares ~80% of the code path with a normal user withdrawal: build → sign → broadcast → monitor. Resist the temptation to merge them — the differences (no idempotency_key, no Transaction aggregate, no user-facing visibility, hot signing always) are enough to keep them separate. Extract a shared helper `_build_sign_broadcast_internal_transfer` if duplication grows.
- The `target_buffer` must be in the SAME asset as the rebalance target. Native rebalance leaves native target_buffer; ERC-20 rebalance leaves ERC-20 target_buffer (native gas is independently managed). Document inline.
- The 4-hour cron is conservative — for testnet portfolio demos, reviewers may expect to see a rebalance within minutes of depositing. Two ways to handle: (a) lower default to 30min for portfolio demo (can revert post-demo); (b) expose an admin "trigger now" button in `phase3-admin-008`. Recommend (b) — keeps prod schedule sensible.
- The "fee race" between user withdrawal and rebalance (AC-07) is the kind of subtle interaction reviewers love to spot. The "rebalance loses gracefully" answer is correct architecturally; a more aggressive design would lock the wallet during rebalance, but that hurts UX.
- Solana SPL rebalance has the additional ATA-creation cost on first rebalance per user (cold's SPL ATA doesn't exist yet). Test this explicitly: first rebalance creates the ATA + transfers; subsequent rebalances just transfer.

---

## Risk / Friction

- The 6 thresholds in the seed data are educated guesses. Real numbers depend on: (a) Sepolia ETH is essentially free at faucet rates, so a 0.5 ETH threshold rarely triggers in casual demo; (b) Shasta TRX is also free; (c) Devnet SOL airdrops are 1 SOL at a time, so 5 SOL threshold rarely triggers. **Tune thresholds for portfolio demo visibility** — if the rebalance never triggers in demos, the architectural feature is invisible to reviewers. Lower thresholds for the demo seed data than for "real" defaults: e.g., ETH threshold = 0.05 ETH (common faucet drip size), so rebalance triggers visibly. Document this is a portfolio-tuning choice, not production-realistic.
- The "no automatic retry" decision (AC-05) is correct simplicity but means a buggy chain RPC or transient KMS issue could leave funds on hot for 4-8 hours. For testnet portfolio scope this is acceptable. Sentry alert (AC-10) catches sustained issues.
- A reviewer who reads this brief deeply might ask: "what stops a malicious admin from setting all `enabled=false` and accumulating funds on hot for an attack?" Answer: the admin role's UPDATE on `custody.rebalance_config` is gated (admin auth from phase1-admin-002); changes are auditable via the audit_log subscriber listening to admin events; the rebalance config table itself has audit triggers (out of scope here, V2 polish). Document the gap.
- The handler `on_rebalance_tx_confirmed` (AC-04) needs to filter only rebalance-related confirmations from the chain.TransactionConfirmed firehose. Use a `tx_hash` lookup against an in-memory or Redis-cached set of "in-flight rebalance txs" populated when broadcasting. Cleaner: store the rebalance tx_hash in a small `custody.in_flight_rebalances` table (similar to outbox pending). Don't try to identify rebalance txs by chain inspection — the metadata is on our side.
