import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TotpRoute from "@/routes/totp";
import { ApiError } from "@/auth/types";

vi.mock("@/auth/api", () => ({
  adminTotpVerify: vi.fn(),
}));

import { adminTotpVerify } from "@/auth/api";

const mockedTotp = vi.mocked(adminTotpVerify);

function LocationProbe({ id }: { id: string }) {
  const location = useLocation();
  const state = (location.state ?? {}) as { lockedMessage?: string };
  return (
    <div data-testid={id}>
      {location.pathname}|{state.lockedMessage ?? ""}
    </div>
  );
}

function renderTotp(opts: { hasCookie?: boolean } = {}) {
  if (opts.hasCookie ?? true) {
    document.cookie = "admin_pre_totp=abc123; path=/";
  } else {
    document.cookie =
      "admin_pre_totp=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  }
  return render(
    <MemoryRouter initialEntries={["/totp"]}>
      <Routes>
        <Route path="/totp" element={<TotpRoute />} />
        <Route
          path="/dashboard"
          element={<LocationProbe id="dashboard-probe" />}
        />
        <Route path="/login" element={<LocationProbe id="login-probe" />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("TotpRoute (AC-phase1-admin-002b-02)", () => {
  beforeEach(() => {
    mockedTotp.mockReset();
    // Clear cookies between tests.
    document.cookie =
      "admin_pre_totp=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("submits a valid 6-digit code and navigates to /dashboard", async () => {
    mockedTotp.mockResolvedValueOnce({
      user: {
        id: "11111111-1111-1111-1111-111111111111",
        email: "admin@vaultchain.example",
        actor_type: "admin",
      },
    });
    renderTotp();

    fireEvent.change(screen.getByLabelText(/code/i), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: /verify/i }));

    await waitFor(() =>
      expect(mockedTotp).toHaveBeenCalledWith({ code: "123456" }),
    );
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-probe")).toHaveTextContent(
        "/dashboard",
      );
    });
  });

  it("clears input and shows inline error on identity.totp_invalid", async () => {
    mockedTotp.mockRejectedValueOnce(
      new ApiError({
        status: 401,
        code: "identity.totp_invalid",
        message: "wrong code",
      }),
    );
    renderTotp();

    const input = screen.getByLabelText(/code/i) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "999999" } });
    fireEvent.click(screen.getByRole("button", { name: /verify/i }));

    const error = await screen.findByTestId("admin-totp-error");
    expect(error).toHaveTextContent(/didn't work/i);
    expect(input.value).toBe("");
  });

  it("redirects to /login with locked-until message on identity.user_locked", async () => {
    mockedTotp.mockRejectedValueOnce(
      new ApiError({
        status: 403,
        code: "identity.user_locked",
        message: "Locked.",
        details: { locked_until: "2026-04-28T16:00:00Z" },
      }),
    );
    renderTotp();

    fireEvent.change(screen.getByLabelText(/code/i), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: /verify/i }));

    await waitFor(() => {
      expect(screen.getByTestId("login-probe")).toHaveTextContent(
        /\/login\|Account locked until 2026-04-28T16:00:00Z/,
      );
    });
  });

  it("redirects to /login with info message when pre-totp cookie is absent", async () => {
    renderTotp({ hasCookie: false });
    await waitFor(() => {
      expect(screen.getByTestId("login-probe")).toHaveTextContent(
        /\/login\|Please sign in again\./,
      );
    });
  });
});
