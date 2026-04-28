// Covers AC-08 — clicking the copy-address button on an EmptyWalletCard
// surfaces the Phase-2 stub toast (no clipboard write).

import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { EmptyWalletCard } from "@/components/dashboard/EmptyWalletCard";
import { ToastProvider } from "@/components/ui/toast";

afterEach(() => {
  cleanup();
});

describe("EmptyWalletCard", () => {
  it("empty_wallet_card_copy_address_shows_phase2_toast", async () => {
    render(
      <ToastProvider>
        <MemoryRouter>
          <EmptyWalletCard
            wallet={{
              chain: "ethereum",
              address: "0x000…000",
              empty: true,
              totalUsd: 0,
            }}
          />
        </MemoryRouter>
      </ToastProvider>,
    );
    const user = userEvent.setup();
    await user.click(screen.getByTestId("empty-wallet-ethereum-copy"));
    expect(screen.getByTestId("toast")).toHaveTextContent(
      /Real addresses arrive in Phase 2/i,
    );
  });
});
