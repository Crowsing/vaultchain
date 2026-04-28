// Covers AC-phase1-web-003-02: signup form validation, submit calls
// `postAuthRequest` with mode=signup, navigates to `/auth/sent` on
// 202, and renders the inline error envelope on 4xx.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

import { ApiError } from "@/lib/api-fetch";
import { SignupRoute } from "@/routes/auth/signup";

const postAuthRequestMock = vi.fn();

vi.mock("@/features/auth/api", () => ({
  postAuthRequest: (...args: unknown[]) => postAuthRequestMock(...args),
  postAuthVerify: vi.fn(),
  postTotpEnroll: vi.fn(),
  postTotpEnrollConfirm: vi.fn(),
  postTotpVerify: vi.fn(),
}));

function LocationProbe(): React.JSX.Element {
  const loc = useLocation();
  return (
    <div data-testid="location">
      {loc.pathname}
      {loc.search}
    </div>
  );
}

beforeEach(() => {
  postAuthRequestMock.mockReset();
});

afterEach(() => {
  cleanup();
});

function renderSignup(): ReturnType<typeof render> {
  return render(
    <MemoryRouter initialEntries={["/auth/signup"]}>
      <Routes>
        <Route path="/auth/signup" element={<SignupRoute />} />
        <Route path="/auth/sent" element={<LocationProbe />} />
        <Route path="/auth/login" element={<div data-testid="login-route" />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("SignupRoute (AC-phase1-web-003-02)", () => {
  it("signup_continue_disabled_until_email_valid", async () => {
    renderSignup();
    const user = userEvent.setup();
    const button = screen.getByTestId("signup-continue");
    expect(button).toBeDisabled();

    const input = screen.getByTestId("signup-email");
    await user.type(input, "not-an-email");
    expect(button).toBeDisabled();

    await user.clear(input);
    await user.type(input, "alice@example.com");
    await waitFor(() => expect(button).not.toBeDisabled());
  });

  it("signup_submit_calls_post_auth_request_and_navigates_to_sent", async () => {
    postAuthRequestMock.mockResolvedValue({ status: "queued" });
    renderSignup();
    const user = userEvent.setup();
    await user.type(screen.getByTestId("signup-email"), "alice@example.com");
    await waitFor(() =>
      expect(screen.getByTestId("signup-continue")).not.toBeDisabled(),
    );
    await user.click(screen.getByTestId("signup-continue"));

    await waitFor(() =>
      expect(postAuthRequestMock).toHaveBeenCalledWith({
        email: "alice@example.com",
        mode: "signup",
      }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        /\/auth\/sent\?email=alice%40example\.com&mode=signup/,
      ),
    );
  });

  it("signup_submit_renders_inline_error_on_4xx_envelope", async () => {
    postAuthRequestMock.mockRejectedValue(
      new ApiError({
        status: 400,
        code: "shared.invalid_email",
        message: "Email is invalid.",
        details: null,
        requestId: "req-1",
      }),
    );
    renderSignup();
    const user = userEvent.setup();
    await user.type(screen.getByTestId("signup-email"), "alice@example.com");
    await waitFor(() =>
      expect(screen.getByTestId("signup-continue")).not.toBeDisabled(),
    );
    await user.click(screen.getByTestId("signup-continue"));
    await waitFor(() =>
      expect(screen.getByTestId("signup-submit-error")).toHaveTextContent(
        "Email is invalid.",
      ),
    );
  });
});
