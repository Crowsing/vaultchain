/**
 * Dashboard skeleton — Phase-1 stub-driven (no live wallet/TX data
 * yet). Lays out the sections per AC-phase1-web-004-01:
 *   1. TierBanner (when Tier 0)
 *   2. WelcomeHero
 *   3. Your wallets — three EmptyWalletCards
 *   4. AI banner welcome
 *   5. Recent activity (empty)
 */
import { useSearchParams } from "react-router-dom";

import { AIBannerWelcome } from "@/components/dashboard/AIBannerWelcome";
import { EmptyTxList } from "@/components/dashboard/EmptyTxList";
import { EmptyWalletCard } from "@/components/dashboard/EmptyWalletCard";
import { TierBanner } from "@/components/dashboard/TierBanner";
import { WelcomeHero } from "@/components/dashboard/WelcomeHero";
import { getStubWallets } from "@/stubs/walletsStub";
import { useUserStore } from "@/store/user-store";

function deriveFirstName(email: string | undefined): string {
  if (!email) return "there";
  const local = email.split("@")[0] ?? email;
  // Title-case the first chunk before any separator.
  const head = local.split(/[._-]/)[0] ?? local;
  return head.charAt(0).toUpperCase() + head.slice(1);
}

export function DashboardRoute(): React.JSX.Element {
  const [params] = useSearchParams();
  const user = useUserStore((s) => s.user);

  // AC-02 Storybook hook: `?tier=1` short-circuits the kyc_tier
  // reading so a screenshot review can land on the Tier-1 layout.
  const tierOverride = params.get("tier");
  const tier: 0 | 1 =
    tierOverride === "1" || (user?.kyc_tier ?? 0) >= 1 ? 1 : 0;

  const firstName = deriveFirstName(user?.email);
  const wallets = getStubWallets();

  return (
    <div data-testid="dashboard" className="flex flex-col gap-6">
      {tier === 0 ? <TierBanner variant="tier0" /> : null}
      <WelcomeHero firstName={firstName} tier={tier} />

      <section className="flex flex-col gap-3" data-testid="wallets-section">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-text-muted">
          Your wallets
        </h3>
        <div
          data-testid="wallets-grid"
          className="grid grid-cols-1 gap-4 md:grid-cols-3"
        >
          {wallets.map((w) => (
            <EmptyWalletCard key={w.chain} wallet={w} />
          ))}
        </div>
      </section>

      <AIBannerWelcome firstName={firstName} />

      <EmptyTxList />
    </div>
  );
}
