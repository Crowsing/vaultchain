import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthGuard } from "@/auth/AuthGuard";
import { useAdminAuthStore } from "@/auth/store";
import { ApiError } from "@/auth/types";

vi.mock("@/auth/api", () => ({
  adminMe: vi.fn(),
  adminLogout: vi.fn(),
}));

import { adminLogout, adminMe } from "@/auth/api";

const mockedMe = vi.mocked(adminMe);
const mockedLogout = vi.mocked(adminLogout);

function LocationProbe({ id }: { id: string }) {
  const location = useLocation();
  return <div data-testid={id}>{location.pathname}</div>;
}

function renderGuard(initial: string) {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <AuthGuard>
        <Routes>
          <Route path="/" element={<div>landing</div>} />
          <Route path="/login" element={<LocationProbe id="login-probe" />} />
          <Route path="/totp" element={<LocationProbe id="totp-probe" />} />
          <Route
            path="/dashboard"
            element={<div data-testid="dashboard-probe">dashboard</div>}
          />
        </Routes>
      </AuthGuard>
    </MemoryRouter>,
  );
}

describe("AuthGuard (AC-phase1-admin-002b-03)", () => {
  beforeEach(() => {
    mockedMe.mockReset();
    mockedLogout.mockReset();
    act(() => {
      useAdminAuthStore.setState({ user: null, bootstrapped: false });
    });
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("hydrates the auth store from /me on success", async () => {
    mockedMe.mockResolvedValueOnce({
      id: "11111111-1111-1111-1111-111111111111",
      email: "admin@vaultchain.example",
      full_name: "Demo Admin",
      role: "admin",
      last_login_at: null,
    });

    renderGuard("/dashboard");

    await waitFor(() => {
      expect(screen.getByTestId("dashboard-probe")).toBeInTheDocument();
    });
    expect(useAdminAuthStore.getState().user?.email).toBe(
      "admin@vaultchain.example",
    );
    expect(mockedMe).toHaveBeenCalledTimes(1);
  });

  it("redirects to /login on identity.session_required (401) for protected route", async () => {
    mockedMe.mockRejectedValueOnce(
      new ApiError({
        status: 401,
        code: "identity.session_required",
        message: "no session",
      }),
    );

    renderGuard("/dashboard");

    await waitFor(() => {
      expect(screen.getByTestId("login-probe")).toHaveTextContent("/login");
    });
    expect(useAdminAuthStore.getState().user).toBeNull();
  });

  it("does NOT redirect when already on /login even without a session", async () => {
    mockedMe.mockRejectedValueOnce(
      new ApiError({
        status: 401,
        code: "identity.session_required",
        message: "no session",
      }),
    );

    renderGuard("/login");

    await waitFor(() => {
      expect(screen.getByTestId("login-probe")).toBeInTheDocument();
    });
    // Still on /login, not bouncing infinitely.
    expect(screen.getByTestId("login-probe")).toHaveTextContent("/login");
  });

  it("does NOT redirect when on /totp even without a session yet", async () => {
    mockedMe.mockRejectedValueOnce(
      new ApiError({
        status: 401,
        code: "identity.session_required",
        message: "no session",
      }),
    );

    renderGuard("/totp");

    await waitFor(() => {
      expect(screen.getByTestId("totp-probe")).toBeInTheDocument();
    });
  });

  it("calls /me only once on app load", async () => {
    mockedMe.mockResolvedValueOnce({
      id: "11111111-1111-1111-1111-111111111111",
      email: "admin@vaultchain.example",
      full_name: "Demo Admin",
      role: "admin",
      last_login_at: null,
    });

    renderGuard("/dashboard");
    await waitFor(() => expect(mockedMe).toHaveBeenCalledTimes(1));

    // Re-render under the same store state — bootstrapped flag should
    // suppress further /me calls.
    renderGuard("/dashboard");
    await waitFor(() => {
      expect(useAdminAuthStore.getState().bootstrapped).toBe(true);
    });
    expect(mockedMe).toHaveBeenCalledTimes(1);
  });
});
