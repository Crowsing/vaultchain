// PHASE 1 STUB — replaced in Phase 2 by useWalletsQuery() from custody.

import { CHAIN_ORDER, type ChainId } from "@/lib/chains";

export type StubWallet = {
  chain: ChainId;
  address: string;
  empty: true;
  totalUsd: 0;
};

const PLACEHOLDER_ADDRESS = "0x000…000";

export function getStubWallets(): ReadonlyArray<StubWallet> {
  return CHAIN_ORDER.map((chain) => ({
    chain,
    address: PLACEHOLDER_ADDRESS,
    empty: true as const,
    totalUsd: 0 as const,
  }));
}
