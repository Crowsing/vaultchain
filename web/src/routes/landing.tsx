/**
 * Landing page — pre-auth surface at `/`.
 *
 * AC-phase1-web-003-01: hero one-liner, three feature highlights, two
 * CTAs ("Sign up" / "Try as demo user"). The demo CTA is intentionally
 * a stub — Phase 4 brings the real demo flow.
 */
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/theme-toggle";
import { useToast } from "@/components/ui/toast";

const FEATURES: ReadonlyArray<{ title: string; copy: string }> = [
  {
    title: "Multi-chain custody",
    copy: "Hold ETH, TRX, and SOL under a single account. Real-time balances and one-click sends.",
  },
  {
    title: "KYC compliance",
    copy: "Tier-based limits with a clear path to higher tiers. We handle the regulator side.",
  },
  {
    title: "AI assistant",
    copy: "Ask plain questions about your balances, transactions, or how anything in the app works.",
  },
];

export function LandingRoute(): React.JSX.Element {
  const navigate = useNavigate();
  const { showToast } = useToast();

  return (
    <div
      data-testid="landing"
      className="flex min-h-screen flex-col bg-bg-page text-text-primary"
    >
      <header className="flex items-center justify-between p-4">
        <div className="flex items-center gap-2 text-sm font-semibold tracking-tight text-brand">
          <div
            aria-hidden
            className="h-5 w-5 rounded-md bg-gradient-to-br from-brand to-cyan-500"
          />
          VaultChain
        </div>
        <ThemeToggle />
      </header>
      <main className="flex flex-1 flex-col items-center justify-center gap-10 p-6 text-center">
        <section className="flex max-w-2xl flex-col items-center gap-4">
          <h1 className="text-4xl font-semibold tracking-tight text-text-primary md:text-5xl">
            Custodial multi-chain wallet with an AI assistant.
          </h1>
          <p className="text-base text-text-secondary md:text-lg">
            Sign in with email — no seed phrases, no password resets at 3am.
          </p>
          <div className="mt-2 flex flex-col gap-2 sm:flex-row">
            <Button
              size="lg"
              data-testid="landing-signup"
              onClick={() => navigate("/auth/signup")}
            >
              Sign up
            </Button>
            <Button
              size="lg"
              variant="outline"
              data-testid="landing-demo"
              onClick={() => showToast("Demo coming in Phase 4")}
            >
              Try as demo user
            </Button>
          </div>
          <p className="mt-4 text-xs text-text-muted">
            Already a member?{" "}
            <button
              type="button"
              data-testid="landing-login-link"
              onClick={() => navigate("/auth/login")}
              className="underline-offset-2 hover:underline"
            >
              Sign in
            </button>
          </p>
        </section>

        <section className="grid w-full max-w-3xl grid-cols-1 gap-4 md:grid-cols-3">
          {FEATURES.map((f) => (
            <article
              key={f.title}
              data-testid="landing-feature"
              className="rounded-lg bg-bg-surface p-5 text-left ring-1 ring-border-default"
            >
              <h3 className="text-sm font-semibold text-text-primary">
                {f.title}
              </h3>
              <p className="mt-2 text-sm text-text-secondary">{f.copy}</p>
            </article>
          ))}
        </section>
      </main>
    </div>
  );
}
