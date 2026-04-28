/**
 * AI assistant teaser banner. AC-phase1-web-004-05: Phase 1 has no AI
 * yet, so the banner navigates to `/ai`, which is a placeholder route
 * ("Assistant lands in phase4-ai").
 */
import { useNavigate } from "react-router-dom";

export function AIBannerWelcome({
  firstName,
}: {
  firstName: string;
}): React.JSX.Element {
  const navigate = useNavigate();
  return (
    <button
      type="button"
      data-testid="ai-banner"
      onClick={() => navigate("/ai")}
      className="group flex w-full flex-col items-start gap-2 rounded-lg bg-gradient-to-br from-bg-surface to-bg-surface-raised p-5 text-left ring-1 ring-border-default transition hover:ring-brand"
    >
      <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-brand">
        <span aria-hidden>✦</span>
        Assistant · Say hello
      </p>
      <p className="text-sm text-text-primary">
        Hi {firstName}. I'm your VaultChain assistant. Ask me anything about how
        the wallet works, or how to verify your identity.
      </p>
    </button>
  );
}
