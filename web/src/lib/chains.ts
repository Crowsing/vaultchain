/**
 * Single source of truth for chain → presentation metadata.
 *
 * Both the dashboard's `EmptyWalletCard` and the Phase-2 production
 * `WalletCard` import from this. Colors are hex literals because the
 * design tokens are general-purpose (text/bg/surface) — chain
 * gradients are domain-specific. Updating any chain's identity
 * happens in exactly one place.
 */
export type ChainId = "ethereum" | "tron" | "solana";

export type ChainTheme = {
  id: ChainId;
  label: string;
  ticker: string;
  /** Two-stop linear gradient endpoints, applied as
   *  `bg-[image:linear-gradient(135deg,from,_to)]`. */
  from: string;
  to: string;
};

export const CHAIN_THEMES: Record<ChainId, ChainTheme> = {
  ethereum: {
    id: "ethereum",
    label: "Ethereum",
    ticker: "ETH",
    from: "#627eea",
    to: "#3b5cdb",
  },
  tron: {
    id: "tron",
    label: "Tron",
    ticker: "TRX",
    from: "#ef4444",
    to: "#b91c1c",
  },
  solana: {
    id: "solana",
    label: "Solana",
    ticker: "SOL",
    from: "#9945ff",
    to: "#14f195",
  },
};

export const CHAIN_ORDER: ReadonlyArray<ChainId> = [
  "ethereum",
  "tron",
  "solana",
];
