---
ac_count: 8
blocks:
- phase2-web-007
- phase2-notifications-001
complexity: M
context: faucet
depends_on:
- phase2-chains-002
- phase2-custody-002
- phase2-wallet-001
- phase2-ledger-002
estimated_hours: 4
id: phase2-faucet-001
phase: 2
sdd_mode: strict
state: ready
title: Sepolia faucet (own funded wallet, rate-limited, mock USDC)
touches_adrs: []
---

# Brief: phase2-faucet-001 — Sepolia faucet (own funded wallet, rate-limited, mock USDC)


## Context

Per spec `04-funding-flow.md`, VaultChain hosts its own funded faucet wallet so users can self-serve testnet tokens without leaving the app. For Phase 2 (Ethereum only):

- **Native ETH faucet:** "Quick fund · 0.05 ETH · once per day" — VaultChain's faucet wallet is pre-funded by the operator from real Sepolia faucets, drips 0.05 ETH per request.
- **Mock USDC faucet:** "Quick fund · 100 USDC" — the operator deploys a mock ERC-20 USDC contract once at deploy time; the faucet calls `mint(user_address, 100 * 10^6)` on it. Phase 2 mock USDC contract address is stored in `chains/infra/ethereum_constants.py`.
- **Rate limit:** 1 quick-fund per user per chain per asset per 24 hours. Enforced via Redis key `faucet:ratelimit:<user_id>:<chain>:<asset>` with 86400s TTL.

The faucet flow:
1. User clicks "Quick fund 0.05 ETH" in the funding UI.
2. Frontend calls `POST /api/v1/faucet/request` with `{chain: 'ethereum', asset: 'ETH'}`.
3. Backend validates the rate limit; if limited, returns 429 with `Retry-After` seconds remaining.
4. Backend constructs an `UnsignedTx` from faucet wallet → user wallet for 0.05 ETH (via `Chains.build_send_tx`).
5. Backend signs via Custody (the faucet wallet's private key is in the same `custody.hot_wallets` table, owned by a synthetic `system_user` UUID).
6. Backend broadcasts; receipt monitor tracks confirmation.
7. On `chain.TransactionConfirmed` for this faucet tx, the faucet handler publishes `faucet.QuickFundCompleted` event.
8. Ledger's `on_faucet_drip` subscriber (per `ledger-002` AC-04) posts the entry: debit `faucet_pool:<chain>:<asset>`, credit `user_hot_wallet:<user>:<chain>:<asset>`.
9. User's dashboard sees the balance update via SSE.

**Important asymmetry:** the faucet wallet uses the same Custody infrastructure as user wallets. There's no special "faucet-only signing" path. The synthetic `system_user` UUID owns the faucet wallets one-per-chain. This keeps the architecture clean.

The mock USDC contract is deployed by the operator at first deploy. The deploy step is documented in the runbook as a one-time `forge create` command. The contract address goes into env (`MOCK_USDC_SEPOLIA_ADDRESS`). The faucet's USDC drip calls `transfer(user, 100e6)` from the faucet wallet (which holds the minted supply), NOT `mint(user, 100e6)` — this means the faucet wallet must hold a large initial USDC balance, also documented as a deploy step.

---

## Architecture pointers

- **Layer:** application + delivery + infra. New small bounded context `faucet/`.
- **Packages touched:**
  - `faucet/domain/value_objects/faucet_request.py`
  - `faucet/domain/errors.py` (`FaucetRateLimited`, `FaucetUnavailable`, `FaucetExhausted`)
  - `faucet/application/use_cases/request_quick_fund.py`
  - `faucet/application/handlers/on_faucet_tx_confirmed.py` (subscribes `chain.TransactionConfirmed` for tx_hashes originated by faucet)
  - `faucet/infra/redis_rate_limit.py`
  - `faucet/delivery/router.py` (`POST /api/v1/faucet/request`, `GET /api/v1/faucet/status`)
  - Composition root: instantiate the synthetic `system_user_id` constant, ensure faucet wallets are provisioned at deploy
- **Reads:** Redis (rate-limit), Wallet (user's address), Custody (faucet wallet's), Chains.
- **Writes:** Redis (rate-limit set), via Chains.broadcast (on-chain), via outbox (faucet events).
- **Publishes events:** `faucet.QuickFundRequested{user_id, chain, asset, amount, faucet_tx_id}`, `faucet.QuickFundCompleted{user_id, chain, asset, amount, tx_hash}`, `faucet.QuickFundFailed{user_id, chain, asset, reason}`. All registered.
- **Migrations:** none (faucet wallets use existing `custody.hot_wallets`; rate limit lives in Redis).
- **OpenAPI:** 2 new endpoints.

---

## Acceptance Criteria

- **AC-phase2-faucet-001-01:** Given the synthetic `SYSTEM_USER_ID = UUID('00000000-0000-0000-0000-000000000001')` (constant), when first deploy runs `ProvisionUserWallets(SYSTEM_USER_ID)` for `chain='ethereum'`, then a faucet wallet is created in `custody.hot_wallets`. The faucet wallet's address is exposed via `GET /admin/api/v1/faucet/wallet` (admin-only, for the operator to send funds to it). Phase 2 documents this provisioning as a one-time bootstrap step in the runbook.

- **AC-phase2-faucet-001-02:** Given an authenticated user, when `POST /api/v1/faucet/request {chain: 'ethereum', asset: 'ETH'}` is called, then: (1) check rate limit Redis key `faucet:ratelimit:<user_id>:ethereum:ETH` — if exists, return `429 faucet.rate_limited` with `Retry-After: <ttl_seconds>`; (2) check faucet wallet balance — if below `0.05 ETH × 5` (5x safety margin), return `503 faucet.exhausted` with operator-facing message in body; (3) check user's wallet exists for the chain; (4) create a Transaction via Transactions context with `from=faucet_address, to=user_address, amount=0.05 ETH, idempotency_key=uuid4()`; (5) trigger the same `confirm_with_totp`-equivalent path but bypassing TOTP (the faucet doesn't need TOTP — it's an internal system action; a separate `confirm_system_action` use case in transactions skips TOTP for `system_user_id` requests); (6) SET rate-limit Redis key with TTL=86400; (7) publish `faucet.QuickFundRequested`; (8) return `{transaction_id, status: 'broadcasting', estimated_arrival: '~30 seconds'}`.

- **AC-phase2-faucet-001-03:** Given a faucet USDC request `POST /api/v1/faucet/request {chain: 'ethereum', asset: 'USDC'}`, when handled, then it: (1) same rate-limit check (separate key `faucet:ratelimit:<user>:ethereum:USDC`); (2) constructs an ERC-20 transfer tx with `to=MOCK_USDC_ADDRESS, data=transfer(user_address, 100e6)`; (3) the rest mirrors AC-02.

- **AC-phase2-faucet-001-04:** Given the chain monitor publishes `chain.TransactionConfirmed` for a faucet-originated transaction, when the subscriber `on_faucet_tx_confirmed` fires, then it: (1) checks if the tx was originated by the faucet (lookup by `from_address == faucet_wallet_address`); (2) if yes, publishes `faucet.QuickFundCompleted{user_id, chain, asset, amount, tx_hash}`; (3) if no, no-op. Identification by `from_address` keeps the subscriber stateless — no separate "faucet transactions" table.

- **AC-phase2-faucet-001-05:** Given `GET /api/v1/faucet/status?chain=ethereum`, when called by an authenticated user, then returns `{available: {ETH: {amount: '0.05', rate_limit_remaining_seconds: 0 | <int>, last_drip_at: ISO8601 | null}, USDC: {amount: '100', ...}}, faucet_wallet_balance: {ETH: '<approx>', USDC: '<approx>'}}`. The balance is informational; if low, frontend can show "faucet running low — try external faucet" hint. Cached server-side for 30s.

- **AC-phase2-faucet-001-06:** Given a faucet request and the faucet wallet has insufficient ETH for both the drip + gas (transient outage if operator hasn't refilled), when broadcast attempts, then `Chains.broadcast` raises `InsufficientGas`; the use case catches it, publishes `faucet.QuickFundFailed{reason: 'faucet_exhausted'}`, **does NOT consume the rate-limit slot** (DEL the Redis key before returning), returns `503 faucet.exhausted`. User can retry without burning their daily quota.

- **AC-phase2-faucet-001-07:** Given a malicious user attempting to spam-call `/faucet/request`, when they hit it twice in quick succession (race), then: the rate-limit Redis SET uses `SET key value NX EX 86400` (atomic; fails on existing key). First request succeeds; second gets the `key already exists` response → 429. **No race-condition burst possible** thanks to atomic SET-NX.

- **AC-phase2-faucet-001-08:** Given the runbook documentation, when committed, then `docs/runbook.md` has a new section "Faucet operations": (1) initial deployment steps for the mock USDC contract via `forge create MockUSDC --rpc-url $ETH_RPC_URL_PRIMARY --private-key $DEPLOYER_KEY` with the contract source committed to `infra/contracts/MockUSDC.sol`; (2) faucet wallet funding steps (operator obtains 5 ETH from a real Sepolia faucet, sends to `SYSTEM_USER_ID`'s ETH address); (3) USDC minting steps (operator calls `mint(faucet_address, 1_000_000 * 10^6)` once after deploy); (4) refill cadence (manual when balance < 1 ETH).

- **AC-phase2-faucet-001-09:** Given the deploy CI (from `phase1-deploy-001`), when running migrations against a fresh DB, then a post-migration hook attempts `ProvisionUserWallets(SYSTEM_USER_ID)` and is idempotent (returns existing wallets). The hook lives in `backend/cli/post_migrate.py`. **The mock USDC deploy is NOT automated** — it's a one-time operator step (deploying a Solidity contract from CI is overkill for a demo).

- **AC-phase2-faucet-001-10:** Given the `confirm_system_action` use case in Transactions (introduced here as a small extension to `transactions-002`), when invoked, then it skips the TOTP check, all other validation runs unchanged. Authorization: the caller must be the faucet use case (verified via a `system_action_token` parameter that the faucet generates and passes; not a security boundary, just a hygiene marker). Phase 3's withdrawal-approval flow uses the same `confirm_system_action` pattern for admin-approved txs.

- **AC-phase2-faucet-001-11:** Given the test environment, when adapter tests run, then Anvil testcontainer hosts the faucet flow end-to-end: deploy mock USDC, send ETH from a test "operator" account to the faucet wallet, request a faucet drip via the API, advance blocks, assert `faucet.QuickFundCompleted` published and Ledger posting created.

---

## Out of Scope

- Tron and Solana faucets: Phase 3 (Solana uses native airdrop on devnet; Tron uses external faucets only per spec 04).
- Real Circle USDC faucet integration: rejected — requires Alchemy login per spec 04, can't proxy on user's behalf. External link only (in frontend brief).
- External faucet deep-link integration: `phase2-web-007` (frontend only).
- Captcha for rate-limit (sepolia-faucet.pk910.de style): not needed — auth + Redis rate limit is sufficient for portfolio scope.
- Variable drip amounts (1 ETH for VIP users, etc.): never.
- Auto-refill from Mainnet (impossible on testnet): never.
- Admin "force drip" override: V2.

---

## Dependencies

- **Code dependencies:** `phase2-chains-002` (build/broadcast/monitor), `phase2-custody-002` (sign — faucet uses same Custody), `phase2-wallet-001` (provision faucet wallets), `phase2-transactions-002` (extends with `confirm_system_action`).
- **Data dependencies:** Mock USDC contract deployed to Sepolia; faucet wallets funded.
- **External dependencies:** Sepolia ETH (operator obtains from external faucet); `forge` for the one-time contract deploy.

---

## Test Coverage Required

- [ ] **Application tests:** `tests/faucet/application/test_request_quick_fund.py` — happy path ETH, happy path USDC, rate-limited (429), faucet-exhausted (503), no wallet (404). Uses Fakes. Covers AC-02, AC-03, AC-06, AC-07.
- [ ] **Application tests:** `tests/faucet/application/test_on_faucet_tx_confirmed.py` — fires with faucet-originated tx, asserts `QuickFundCompleted` published; with non-faucet tx, asserts no-op. Covers AC-04.
- [ ] **Adapter tests:** `tests/faucet/infra/test_redis_rate_limit.py` — Redis testcontainer; SET-NX race test, TTL respected. Covers AC-07.
- [ ] **Adapter tests:** `tests/faucet/infra/test_faucet_e2e_anvil.py` — Anvil; deploys mock USDC, runs full faucet flow for both ETH and USDC, asserts confirmations. Covers AC-11.
- [ ] **Contract tests:** `tests/api/test_faucet_endpoints.py` — TestClient, full request → confirm flow with mocked chain (or Anvil), rate limit enforcement, status endpoint shape. Covers AC-02, AC-03, AC-05.
- [ ] **E2E:** indirect via `phase2-web-007` Playwright spec for the funding UI.

---

## Done Definition

- [ ] All ACs verified by named test cases.
- [ ] All test categories above implemented and passing locally.
- [ ] `import-linter` contracts pass (faucet imports Transactions / Chains / Wallet via ports only).
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass.
- [ ] OpenAPI schema diff: 2 new endpoints documented; `docs/api-contract.yaml` committed.
- [ ] Three new domain events registered.
- [ ] `infra/contracts/MockUSDC.sol` committed (a minimal ERC-20 with `name='Mock USDC', symbol='USDC', decimals=6, mint(address, uint256)` — owner-only mint).
- [ ] Runbook section "Faucet operations" written.
- [ ] Single PR. Conventional commit: `feat(faucet): sepolia quick-fund + mock usdc [phase2-faucet-001]`.

---

## Implementation Notes

- The synthetic `SYSTEM_USER_ID` is a hardcoded UUID in `shared/constants.py`. Document inline that this UUID has special meaning and should never be assigned to real users.
- The MockUSDC contract should be ~30 lines of Solidity using OpenZeppelin's `ERC20` base. Compile via `forge build` (operator-side), commit the resulting bytecode to `infra/contracts/MockUSDC.json` for reference. The deploy command goes in the runbook.
- The "faucet wallet runs out → don't consume rate-limit slot" pattern (AC-06) is important UX. Without it, an exhausted faucet eats the user's daily quota and they can't try again for 24h. SET-NX-then-DEL on failure is the right pattern.
- The `confirm_system_action` extension to Transactions (AC-10) is a small change but lives in `transactions-002`'s code. Document this brief reaches back into another brief's package — note in PR.
- The faucet wallet balance check (AC-02 step 2, AC-05) does NOT call the chain RPC — it reads from the Ledger's `faucet_pool` account balance via `GetAccountBalance`. The Ledger debits faucet_pool on every drip; if the operator doesn't refill, the Ledger balance goes to zero and the check trips before broadcasting. **This is one of the cleaner uses of the Ledger** — it provides synthetic accounting for system resources. Document in PR.

---

## Risk / Friction

- The mock USDC deployment step is a footgun for first-time deployers. The runbook section needs to be explicit: full forge command, expected output, the env var that needs updating. Add a smoke test in the deploy runbook: "after deploying USDC, run `cast call $MOCK_USDC_ADDRESS 'name()(string)' --rpc-url $ETH_RPC_URL_PRIMARY` and verify it returns `Mock USDC`."
- The faucet wallet is a single point of trust. If its private key leaks, an attacker drains the testnet ETH/USDC. For testnet portfolio scope this is fine (no real value), but document explicitly that the faucet wallet is NOT a model for production.
- The `system_user_id` provisioning at deploy time creates a wallet that's visible in `wallet.wallets`. The Wallet endpoint already filters by user_id (each user only sees their own); admin endpoints in Phase 3 should NOT show the system wallet to the admin viewer (it would be confusing). Add a filter clause in Phase 3 admin queries.
- The 5x safety margin on faucet ETH (AC-02 step 2) is conservative. Tune in operations: if the faucet runs out frequently, increase the operator-side refill cadence rather than lowering the margin.
- The ledger's `faucet_pool` account starts with no balance — the first drip would post a debit on a zero-balance account, making it negative. **However, faucet_pool is NOT a `user_hot_wallet`**, so the "user account never negative" property test from `ledger-001` doesn't apply. faucet_pool's balance going negative reflects "the faucet has dispensed more than the operator funded" — a logical inconsistency that triggers reconciliation alerts. Document the balance-check pattern in the runbook and resolve by adding an initial credit posting at deploy time (`debit external_chain, credit faucet_pool` for the operator's deposit amount).
