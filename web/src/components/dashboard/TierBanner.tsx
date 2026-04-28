/**
 * Tier-0 verification banner. AC-phase1-web-004-01 places it at the
 * top of the dashboard; AC-07 makes it dismissable for the current
 * session via `sessionStorage` (re-appears on next page load — the
 * pressure to verify is intentional).
 */
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";

const STORAGE_KEY = "vc-tier-banner-dismissed";

function readDismissed(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.sessionStorage.getItem(STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export function TierBanner({
  variant = "tier0",
}: {
  variant?: "tier0";
}): React.JSX.Element | null {
  const [dismissed, setDismissed] = useState<boolean>(() => readDismissed());
  const { showToast } = useToast();

  useEffect(() => {
    if (!dismissed) return;
    try {
      window.sessionStorage.setItem(STORAGE_KEY, "true");
    } catch {
      /* ignore storage errors */
    }
  }, [dismissed]);

  if (variant !== "tier0" || dismissed) return null;

  return (
    <section
      role="region"
      aria-label="Identity verification banner"
      data-testid="tier-banner"
      className="flex items-start justify-between gap-4 rounded-lg bg-gradient-to-br from-brand to-cyan-500 p-5 text-text-on-brand shadow-md md:items-center"
    >
      <div className="flex flex-col gap-1">
        <p className="text-sm font-semibold uppercase tracking-wider opacity-90">
          Tier 0 — verification needed
        </p>
        <p className="text-base">
          Verify your identity to send transactions and unlock higher limits.
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          data-testid="tier-banner-cta"
          onClick={() => showToast("KYC flow coming in Phase 3")}
          className="border-text-on-brand bg-transparent text-text-on-brand hover:bg-bg-surface-raised hover:text-text-primary"
        >
          Start verification
        </Button>
        <button
          type="button"
          aria-label="Dismiss"
          data-testid="tier-banner-dismiss"
          onClick={() => setDismissed(true)}
          className="flex h-8 w-8 items-center justify-center rounded-md text-text-on-brand opacity-70 hover:opacity-100"
        >
          ×
        </button>
      </div>
    </section>
  );
}
