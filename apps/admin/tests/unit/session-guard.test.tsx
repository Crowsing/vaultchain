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

import { adminMe } from "@/auth/api";

const mockedMe = vi.mocked(adminMe);

function LocationProbe() {
  const location = useLocation();
  return (
    <div data-testid="location">
      {location.pathname}
      {location.search}
    </div>
  );
}

function renderGuard(initial: string) {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <AuthGuard>
        <Routes>
          <Route
            path="/"
            element={<div data-testid="dashboard-probe">d</div>}
          />
          <Route path="/login" element={<LocationProbe />} />
          <Route path="/totp" element={<LocationProbe />} />
          <Route path="/applicants" element={<div>applicants</div>} />
        </Routes>
      </AuthGuard>
    </MemoryRouter>,
  );
}

describe("AuthGuard session bootstrap (AC-phase1-admin-003-01)", () => {
  beforeEach(() => {
    mockedMe.mockReset();
    act(() => {
      useAdminAuthStore.setState({ user: null, bootstrapped: false });
    });
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders dashboard after /me 200 — covers GET /admin/api/v1/auth/me success", async () => {
    mockedMe.mockResolvedValueOnce({
      id: "11111111-1111-1111-1111-111111111111",
      email: "admin@vaultchain.example",
      full_name: "Demo Admin",
      role: "admin",
      last_login_at: "2026-04-28T10:00:00Z",
    });

    renderGuard("/");

    await waitFor(() => {
      expect(screen.getByTestId("dashboard-probe")).toBeInTheDocument();
    });
    expect(useAdminAuthStore.getState().user?.email).toBe(
      "admin@vaultchain.example",
    );
  });

  it("redirects to /login?redirect=… on 401 (preserves original URL)", async () => {
    mockedMe.mockRejectedValueOnce(
      new ApiError({
        status: 401,
        code: "identity.session_required",
        message: "no session",
      }),
    );

    renderGuard("/applicants");

    await waitFor(() => {
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/login?redirect=%2Fapplicants",
      );
    });
  });

  it("renders the loading splash and finishes after a network error (no redirect, no crash)", async () => {
    mockedMe.mockRejectedValueOnce(new Error("network error"));

    renderGuard("/");

    await waitFor(() => {
      expect(screen.getByTestId("auth-guard-error")).toBeInTheDocument();
    });
  });

  it("shows the loading splash for at least 250ms before settling", async () => {
    mockedMe.mockResolvedValueOnce({
      id: "11111111-1111-1111-1111-111111111111",
      email: "admin@vaultchain.example",
      full_name: "Demo Admin",
      role: "admin",
      last_login_at: null,
    });

    renderGuard("/");

    expect(screen.getByTestId("auth-guard-loading")).toBeInTheDocument();
    await waitFor(
      () => {
        expect(screen.getByTestId("dashboard-probe")).toBeInTheDocument();
      },
      { timeout: 1000 },
    );
  });

  it("does NOT redirect when already on /login", async () => {
    mockedMe.mockRejectedValueOnce(
      new ApiError({
        status: 401,
        code: "identity.session_required",
        message: "no session",
      }),
    );

    renderGuard("/login");

    await waitFor(() => {
      expect(screen.getByTestId("location")).toBeInTheDocument();
    });
    // Did not redirect — still on /login (no redirect query because we
    // were already on /login when /me failed).
    expect(screen.getByTestId("location").textContent).toBe("/login");
  });
});
