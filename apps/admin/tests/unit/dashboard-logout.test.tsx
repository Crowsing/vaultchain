import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DashboardRoute from "@/routes/dashboard";
import { useAdminAuthStore } from "@/auth/store";

vi.mock("@/auth/api", () => ({
  adminLogout: vi.fn(),
}));

import { adminLogout } from "@/auth/api";

const mockedLogout = vi.mocked(adminLogout);

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

describe("Dashboard logout (AC-phase1-admin-002b-03 — logout wiring)", () => {
  beforeEach(() => {
    mockedLogout.mockReset();
    act(() => {
      useAdminAuthStore.setState({
        user: {
          id: "11111111-1111-1111-1111-111111111111",
          email: "admin@vaultchain.example",
          full_name: "Demo Admin",
          role: "admin",
          last_login_at: null,
        },
        bootstrapped: true,
      });
    });
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calls POST /logout, clears the store, and redirects to /login", async () => {
    mockedLogout.mockResolvedValueOnce();

    render(
      <MemoryRouter initialEntries={["/dashboard"]}>
        <Routes>
          <Route path="/dashboard" element={<DashboardRoute />} />
          <Route path="/login" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByTestId("admin-logout"));

    await waitFor(() => expect(mockedLogout).toHaveBeenCalledTimes(1));
    await waitFor(() => {
      expect(screen.getByTestId("location")).toHaveTextContent("/login");
    });
    expect(useAdminAuthStore.getState().user).toBeNull();
  });
});
