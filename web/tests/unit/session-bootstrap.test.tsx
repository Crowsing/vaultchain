// Covers AC-01 (bootstrap → splash → render / redirect / error), AC-05
// (mid-session 401 dispatches `session:expired` and the gate navigates),
// AC-07 (visibilitychange → silent re-validate).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { ApiError } from "@/lib/api-fetch";
import { sessionEvents } from "@/auth/session-events";
import { SessionGate } from "@/components/SessionGate";
import { useUserStore } from "@/store/user-store";

vi.mock("@/lib/api-fetch", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/api-fetch")>("@/lib/api-fetch");
  return {
    ...actual,
    apiFetch: vi.fn(),
  };
});

const meOk = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "alice@example.com",
  status: "verified",
  kyc_tier: 0,
  totp_enrolled: true,
  created_at: "2026-04-28T09:00:00+00:00",
};

beforeEach(() => {
  useUserStore.setState({ user: null, status: "idle" });
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
});

function renderGate(initialPath = "/dashboard"): ReturnType<typeof render> {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route element={<SessionGate />}>
          <Route path="*" element={<div data-testid="content">DASH</div>} />
        </Route>
        <Route
          path="/auth/login"
          element={<div data-testid="login">LOGIN</div>}
        />
        <Route path="/auth/totp" element={<div data-testid="totp">TOTP</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("SessionGate", () => {
  it("session_bootstrap_renders_splash_then_content_on_200", async () => {
    const { apiFetch } = await import("@/lib/api-fetch");
    vi.mocked(apiFetch).mockResolvedValueOnce(meOk);

    renderGate();

    expect(screen.getByTestId("session-splash")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("content")).toBeInTheDocument();
    });
    expect(useUserStore.getState().status).toBe("authenticated");
    expect(useUserStore.getState().user?.email).toBe("alice@example.com");
  });

  it("session_bootstrap_redirects_to_login_on_401", async () => {
    const { apiFetch } = await import("@/lib/api-fetch");
    vi.mocked(apiFetch).mockRejectedValueOnce(
      new ApiError({
        status: 401,
        code: "identity.unauthenticated",
        message: "no session",
        details: null,
        requestId: "rid",
      }),
    );

    renderGate("/send");
    await waitFor(() => {
      expect(screen.getByTestId("login")).toBeInTheDocument();
    });
    expect(useUserStore.getState().status).toBe("unauthenticated");
  });

  it("session_bootstrap_redirects_to_totp_when_required", async () => {
    const { apiFetch } = await import("@/lib/api-fetch");
    vi.mocked(apiFetch).mockRejectedValueOnce(
      new ApiError({
        status: 401,
        code: "identity.totp_required",
        message: "totp",
        details: null,
        requestId: "rid",
      }),
    );

    renderGate();
    await waitFor(() => {
      expect(screen.getByTestId("totp")).toBeInTheDocument();
    });
  });

  it("session_bootstrap_renders_network_error_on_5xx", async () => {
    const { apiFetch } = await import("@/lib/api-fetch");
    vi.mocked(apiFetch).mockRejectedValueOnce(
      new ApiError({
        status: 503,
        code: "shared.upstream",
        message: "downstream broken",
        details: null,
        requestId: "rid",
      }),
    );

    renderGate();
    await waitFor(() => {
      expect(screen.getByTestId("session-network-error")).toBeInTheDocument();
    });
  });

  it("session_bootstrap_retry_button_runs_again", async () => {
    const { apiFetch } = await import("@/lib/api-fetch");
    vi.mocked(apiFetch)
      .mockRejectedValueOnce(
        new ApiError({
          status: 503,
          code: "shared.upstream",
          message: "downstream broken",
          details: null,
          requestId: "rid",
        }),
      )
      .mockResolvedValueOnce(meOk);

    renderGate();
    await waitFor(() => {
      expect(screen.getByTestId("session-network-error")).toBeInTheDocument();
    });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => {
      expect(screen.getByTestId("content")).toBeInTheDocument();
    });
  });

  it("session_bootstrap_session_expired_navigates_to_login", async () => {
    const { apiFetch } = await import("@/lib/api-fetch");
    vi.mocked(apiFetch).mockResolvedValueOnce(meOk);
    renderGate("/contacts");
    await waitFor(() => {
      expect(screen.getByTestId("content")).toBeInTheDocument();
    });

    act(() => {
      sessionEvents.dispatchEvent(
        new CustomEvent("session:expired", {
          detail: { code: "identity.unauthenticated", status: 401 },
        }),
      );
    });

    await waitFor(() => {
      expect(screen.getByTestId("login")).toBeInTheDocument();
    });
    expect(useUserStore.getState().user).toBeNull();
  });

  it("session_bootstrap_visibility_change_revalidates", async () => {
    const { apiFetch } = await import("@/lib/api-fetch");
    vi.mocked(apiFetch)
      .mockResolvedValueOnce(meOk)
      .mockResolvedValueOnce({
        ...meOk,
        kyc_tier: 1,
      });
    renderGate();
    await waitFor(() => {
      expect(screen.getByTestId("content")).toBeInTheDocument();
    });
    expect(useUserStore.getState().user?.kyc_tier).toBe(0);

    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "visible",
    });
    fireEvent(document, new Event("visibilitychange"));

    await waitFor(() => {
      expect(useUserStore.getState().user?.kyc_tier).toBe(1);
    });
    // Splash should NOT have appeared on the silent re-run.
    expect(screen.getByTestId("content")).toBeInTheDocument();
  });
});
