import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import LoginRoute from "@/routes/login";
import { ApiError } from "@/auth/types";

vi.mock("@/auth/api", () => ({
  adminLogin: vi.fn(),
}));

import { adminLogin } from "@/auth/api";

const mockedAdminLogin = vi.mocked(adminLogin);

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderLogin(
  initialEntries: Array<string | { pathname: string; state: unknown }> = [
    "/login",
  ],
) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <Routes>
        <Route path="/login" element={<LoginRoute />} />
        <Route path="/totp" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("LoginRoute (AC-phase1-admin-002b-01)", () => {
  beforeEach(() => {
    mockedAdminLogin.mockReset();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("submits valid credentials and navigates to /totp", async () => {
    mockedAdminLogin.mockResolvedValueOnce({ pre_totp_required: true });
    renderLogin();

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "admin@vaultchain.example" },
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: "supersecret-passphrase" },
    });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(mockedAdminLogin).toHaveBeenCalledTimes(1));
    expect(mockedAdminLogin).toHaveBeenCalledWith({
      email: "admin@vaultchain.example",
      password: "supersecret-passphrase",
    });
    await waitFor(() => {
      expect(screen.getByTestId("location")).toHaveTextContent("/totp");
    });
  });

  it("rejects malformed email client-side (does not call API)", async () => {
    renderLogin();

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "not-an-email" },
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: "anything" },
    });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText(/valid email/i)).toBeInTheDocument();
    });
    expect(mockedAdminLogin).not.toHaveBeenCalled();
  });

  it("renders inline error on identity.invalid_credentials (401)", async () => {
    mockedAdminLogin.mockRejectedValueOnce(
      new ApiError({
        status: 401,
        code: "identity.invalid_credentials",
        message: "Invalid credentials.",
      }),
    );
    renderLogin();

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "admin@vaultchain.example" },
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: "wrong" },
    });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    const error = await screen.findByTestId("admin-login-error");
    expect(error).toHaveTextContent(/email or password/i);
    expect(screen.queryByTestId("location")).toBeNull();
  });

  it("renders locked-until message on identity.user_locked (403)", async () => {
    mockedAdminLogin.mockRejectedValueOnce(
      new ApiError({
        status: 403,
        code: "identity.user_locked",
        message: "Locked.",
        details: { locked_until: "2026-04-28T16:00:00Z" },
      }),
    );
    renderLogin();

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "admin@vaultchain.example" },
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: "anything-long-enough" },
    });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    const error = await screen.findByTestId("admin-login-error");
    expect(error).toHaveTextContent(
      /Account locked until 2026-04-28T16:00:00Z/i,
    );
  });

  it("preserves locked message from router location.state (e.g. arrived from /totp)", () => {
    renderLogin([
      {
        pathname: "/login",
        state: { lockedMessage: "Account locked until 2026-04-29T01:23:45Z" },
      },
    ]);

    expect(screen.getByTestId("admin-login-error")).toHaveTextContent(
      /Account locked until 2026-04-29T01:23:45Z/i,
    );
  });
});
