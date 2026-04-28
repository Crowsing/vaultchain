// Covers AC-02 (DesktopShell renders the seven primary nav items + user
// card), AC-03 (MobileShell renders the five tab items + ≥44px tap
// targets), AC-06 (404 catch-all renders inside the shell when authed).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/shell/AppShell";
import { MOBILE_TABS, NAV } from "@/components/shell/nav";
import { NotFoundRoute } from "@/routes/not-found";
import { useUserStore } from "@/store/user-store";

function stubMatchMedia(matches: boolean): void {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((q: string) => ({
      matches,
      media: q,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
}

beforeEach(() => {
  useUserStore.setState({
    user: {
      id: "11111111-1111-1111-1111-111111111111",
      email: "alice@example.com",
      status: "verified",
      kyc_tier: 1,
      totp_enrolled: true,
      created_at: "2026-04-28T09:00:00+00:00",
    },
    status: "authenticated",
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderShell(initialPath = "/dashboard"): ReturnType<typeof render> {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="dashboard" element={<div>D</div>} />
          <Route path="send" element={<div>S</div>} />
          <Route path="*" element={<NotFoundRoute />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("AppShell on desktop viewport", () => {
  beforeEach(() => stubMatchMedia(true));

  it("desktop_shell_renders_seven_nav_items", () => {
    renderShell();
    const sidebar = screen.getByTestId("desktop-sidebar");
    expect(sidebar).toBeInTheDocument();
    for (const n of NAV) {
      expect(screen.getByTestId(`desk-nav-${n.id}`)).toBeInTheDocument();
    }
  });

  it("desktop_shell_marks_active_route", () => {
    renderShell("/send");
    const send = screen.getByTestId("desk-nav-send");
    expect(send.getAttribute("data-active")).toBe("true");
    const dashboard = screen.getByTestId("desk-nav-dashboard");
    expect(dashboard.getAttribute("data-active")).toBe("false");
  });

  it("desktop_shell_shows_user_card", () => {
    renderShell();
    expect(screen.getByText("alice@example.com")).toBeInTheDocument();
    expect(screen.getByText(/Tier 1/)).toBeInTheDocument();
  });

  it("desktop_shell_404_catch_all_renders_inside_shell", () => {
    renderShell("/nope");
    expect(screen.getByTestId("desktop-sidebar")).toBeInTheDocument();
    expect(screen.getByTestId("not-found")).toBeInTheDocument();
  });
});

describe("AppShell on mobile viewport", () => {
  beforeEach(() => stubMatchMedia(false));

  it("mobile_shell_shows_only_five_tab_items", () => {
    renderShell();
    const tabs = screen.getByTestId("mobile-tabs");
    expect(tabs).toBeInTheDocument();
    for (const tabId of MOBILE_TABS) {
      expect(screen.getByTestId(`mob-tab-${tabId}`)).toBeInTheDocument();
    }
    // Receive and Settings are NOT pinned to the bottom bar.
    expect(screen.queryByTestId("mob-tab-receive")).toBeNull();
    expect(screen.queryByTestId("mob-tab-settings")).toBeNull();
  });

  it("mobile_shell_tap_targets_are_at_least_44px", () => {
    renderShell();
    for (const tabId of MOBILE_TABS) {
      const link = screen.getByTestId(`mob-tab-${tabId}`);
      expect(link.className).toMatch(/min-h-\[44px\]|h-14/);
    }
  });

  it("mobile_shell_marks_active_route", () => {
    renderShell("/send");
    const send = screen.getByTestId("mob-tab-send");
    expect(send.getAttribute("data-active")).toBe("true");
  });

  it("mobile_shell_404_catch_all_renders_inside_shell", () => {
    renderShell("/nope");
    expect(screen.getByTestId("mobile-header")).toBeInTheDocument();
    expect(screen.getByTestId("not-found")).toBeInTheDocument();
  });
});
