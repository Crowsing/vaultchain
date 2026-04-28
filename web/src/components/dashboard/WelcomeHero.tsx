/**
 * Welcome hero — Tier-0 and Tier-1 variants per AC-phase1-web-004-01
 * and -02. The Tier-0 hero exists in `empty-states.jsx` design and
 * carries the AI-forward "welcome-eyebrow" sparkle decoration.
 */

export function WelcomeHero({
  firstName,
  tier,
}: {
  firstName: string;
  tier: 0 | 1;
}): React.JSX.Element {
  if (tier === 0) {
    return (
      <section
        data-testid="welcome-hero-tier0"
        className="rounded-lg bg-bg-surface p-6 ring-1 ring-border-default"
      >
        <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-brand">
          <span aria-hidden>✦</span>
          Welcome
        </p>
        <h2 className="mt-2 text-2xl font-semibold tracking-tight text-text-primary">
          Welcome to VaultChain, {firstName}
        </h2>
        <p className="mt-2 max-w-2xl text-sm text-text-secondary">
          Three wallets are ready. Verify your identity to start moving funds.
        </p>
      </section>
    );
  }

  return (
    <section
      data-testid="welcome-hero-tier1"
      className="rounded-lg bg-bg-surface p-6 ring-1 ring-border-default"
    >
      <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">
        Total balance · Tier 1
      </p>
      <p className="mt-2 text-3xl font-semibold tracking-tight text-text-primary">
        $0.00
      </p>
      <p className="mt-2 text-sm text-text-secondary">
        Your wallets are ready. Get tokens to start.
      </p>
    </section>
  );
}
