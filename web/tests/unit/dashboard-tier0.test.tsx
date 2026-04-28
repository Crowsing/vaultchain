// Covers AC-01 (Tier-0 layout), AC-04 (receive navigation), AC-05 (AI
// banner navigation), AC-07 (banner dismiss persistence).

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { ToastProvider } from "@/components/ui/toast";
import { DashboardRoute } from "@/routes/dashboard";
import { useUserStore } from "@/store/user-store";

beforeEach(() => {
  useUserStore.setState({
    user: {
      id: "11111111-1111-1111-1111-111111111111",
      email: "alex.morgan@example.com",
      status: "verified",
      kyc_tier: 0,
      totp_enrolled: true,
      created_at: "2026-04-28T09:00:00+00:00",
    },
    status: "authenticated",
  });
  window.sessionStorage.clear();
});

afterEach(() => {
  cleanup();
});

function renderDashboard(
  initialPath = "/dashboard",
): ReturnType<typeof render> {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/dashboard" element={<DashboardRoute />} />
          <Route
            path="/receive"
            element={<div data-testid="receive-route">RECEIVE</div>}
          />
          <Route path="/ai" element={<div data-testid="ai-route">AI</div>} />
        </Routes>
      </MemoryRouter>
    </ToastProvider>,
  );
}

describe("Dashboard (Tier 0)", () => {
  it("dashboard_tier0_renders_banner_hero_three_wallets_empty_tx", () => {
    renderDashboard();
    expect(screen.getByTestId("tier-banner")).toBeInTheDocument();
    expect(screen.getByTestId("welcome-hero-tier0")).toBeInTheDocument();
    expect(screen.getByText("Welcome to VaultChain, Alex")).toBeInTheDocument();
    expect(screen.getByTestId("empty-wallet-ethereum")).toBeInTheDocument();
    expect(screen.getByTestId("empty-wallet-tron")).toBeInTheDocument();
    expect(screen.getByTestId("empty-wallet-solana")).toBeInTheDocument();
    expect(screen.getByTestId("empty-tx-list")).toBeInTheDocument();
    expect(screen.getByTestId("ai-banner")).toBeInTheDocument();
  });

  it("dashboard_tier0_banner_cta_shows_phase3_toast", async () => {
    renderDashboard();
    const user = userEvent.setup();
    await user.click(screen.getByTestId("tier-banner-cta"));
    expect(screen.getByTestId("toast")).toHaveTextContent(
      /KYC flow coming in Phase 3/i,
    );
  });

  it("dashboard_tier0_dismiss_persists_to_session_storage", async () => {
    renderDashboard();
    const user = userEvent.setup();
    expect(screen.getByTestId("tier-banner")).toBeInTheDocument();
    await user.click(screen.getByTestId("tier-banner-dismiss"));
    expect(screen.queryByTestId("tier-banner")).toBeNull();
    expect(window.sessionStorage.getItem("vc-tier-banner-dismissed")).toBe(
      "true",
    );
  });

  it("dashboard_tier0_share_address_navigates_to_receive_with_chain", async () => {
    renderDashboard();
    const user = userEvent.setup();
    await user.click(screen.getByTestId("empty-wallet-ethereum-receive"));
    expect(screen.getByTestId("receive-route")).toBeInTheDocument();
  });

  it("dashboard_tier0_ai_banner_navigates_to_ai", async () => {
    renderDashboard();
    const user = userEvent.setup();
    await user.click(screen.getByTestId("ai-banner"));
    expect(screen.getByTestId("ai-route")).toBeInTheDocument();
  });

  it("dashboard_tier1_query_param_swaps_hero_and_hides_banner", () => {
    renderDashboard("/dashboard?tier=1");
    expect(screen.queryByTestId("tier-banner")).toBeNull();
    expect(screen.getByTestId("welcome-hero-tier1")).toBeInTheDocument();
  });
});
