/**
 * Empty wallet card — three of them stack on the dashboard for
 * Phase 1's stub data. The "Share address to receive" button
 * navigates to `/receive?wallet=<chain>` (AC-04); the copy-address
 * button surfaces a stub toast (AC-08).
 */
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { CHAIN_THEMES } from "@/lib/chains";
import type { StubWallet } from "@/stubs/walletsStub";

export function EmptyWalletCard({
  wallet,
}: {
  wallet: StubWallet;
}): React.JSX.Element {
  const theme = CHAIN_THEMES[wallet.chain];
  const navigate = useNavigate();
  const { showToast } = useToast();

  return (
    <article
      data-testid={`empty-wallet-${wallet.chain}`}
      className="overflow-hidden rounded-lg ring-1 ring-border-default"
    >
      <div
        aria-hidden
        className="h-2"
        style={{
          backgroundImage: `linear-gradient(135deg, ${theme.from}, ${theme.to})`,
        }}
      />
      <div className="flex flex-col gap-4 bg-bg-surface p-5">
        <header className="flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-text-primary">
              {theme.label}
            </p>
            <p className="text-xs text-text-muted">{theme.ticker}</p>
          </div>
          <p className="text-sm font-medium text-text-secondary">$0.00</p>
        </header>
        <div className="flex items-center justify-between gap-2 rounded-md bg-bg-surface-sunken px-3 py-2 text-xs">
          <code
            className="text-text-muted"
            data-testid={`empty-wallet-${wallet.chain}-address`}
          >
            {wallet.address}
          </code>
          <button
            type="button"
            aria-label={`Copy ${theme.label} address`}
            data-testid={`empty-wallet-${wallet.chain}-copy`}
            onClick={() =>
              showToast("Real addresses arrive in Phase 2 (custody).")
            }
            className="rounded-md px-2 py-1 text-text-secondary hover:bg-bg-surface-raised"
          >
            Copy
          </button>
        </div>
        <Button
          variant="outline"
          size="sm"
          data-testid={`empty-wallet-${wallet.chain}-receive`}
          onClick={() => navigate(`/receive?wallet=${wallet.chain}`)}
        >
          Share address to receive
        </Button>
      </div>
    </article>
  );
}
