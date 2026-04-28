// Covers AC-phase1-web-003-05: 4-step enrollment wizard. Step 2 fetches
// QR + secret. Step 3 confirms; on 3 failures the wizard restarts at
// step 2. Step 4 shows backup codes and the download button.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { ToastProvider } from "@/components/ui/toast";
import { ApiError } from "@/lib/api-fetch";
import { EnrollRoute } from "@/routes/auth/enroll";
import { useAuthStore } from "@/store/auth-store";

const postTotpEnrollMock = vi.fn();
const postTotpEnrollConfirmMock = vi.fn();

vi.mock("@/features/auth/api", () => ({
  postAuthRequest: vi.fn(),
  postAuthVerify: vi.fn(),
  postTotpEnroll: (...args: unknown[]) => postTotpEnrollMock(...args),
  postTotpEnrollConfirm: (...args: unknown[]) =>
    postTotpEnrollConfirmMock(...args),
  postTotpVerify: vi.fn(),
}));

vi.mock("qrcode", () => ({
  default: {
    toString: vi.fn().mockResolvedValue("<svg data-testid='qr-svg'/>"),
  },
}));

const FAKE_ENROLL = {
  secret_for_qr: "JBSWY3DPEHPK3PXP",
  qr_payload_uri:
    "otpauth://totp/VaultChain:alice@example.com?secret=JBSWY3DPEHPK3PXP&issuer=VaultChain",
  backup_codes: [
    "ABCD-1234",
    "EFGH-5678",
    "IJKL-9012",
    "MNOP-3456",
    "QRST-7890",
    "UVWX-1234",
    "YZAB-5678",
    "CDEF-9012",
    "GHIJ-3456",
    "KLMN-7890",
  ],
};

beforeEach(() => {
  postTotpEnrollMock.mockReset().mockResolvedValue(FAKE_ENROLL);
  postTotpEnrollConfirmMock.mockReset();
  useAuthStore.setState({ preTotpToken: "fake-pre-totp-token" });
  if (navigator.clipboard) {
    vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined);
  } else {
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
      configurable: true,
      writable: true,
    });
  }
});

afterEach(() => {
  cleanup();
  useAuthStore.setState({ preTotpToken: null });
});

function renderEnroll(): ReturnType<typeof render> {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={["/auth/enroll"]}>
        <Routes>
          <Route path="/auth/enroll" element={<EnrollRoute />} />
          <Route
            path="/dashboard"
            element={<div data-testid="dashboard-route" />}
          />
        </Routes>
      </MemoryRouter>
    </ToastProvider>,
  );
}

describe("EnrollRoute (AC-phase1-web-003-05)", () => {
  it("enrollment_step1_lists_recommended_apps", () => {
    renderEnroll();
    expect(screen.getByTestId("auth-enroll-step-1")).toBeInTheDocument();
    expect(screen.getByText("1Password")).toBeInTheDocument();
    expect(screen.getByText("Google Authenticator")).toBeInTheDocument();
  });

  it("enrollment_step2_fetches_qr_and_displays_secret", async () => {
    renderEnroll();
    const user = userEvent.setup();
    await user.click(screen.getByTestId("enroll-step1-continue"));

    await waitFor(() =>
      expect(postTotpEnrollMock).toHaveBeenCalledWith("fake-pre-totp-token"),
    );
    await waitFor(() =>
      expect(screen.getByTestId("enroll-secret")).toHaveTextContent(
        FAKE_ENROLL.secret_for_qr,
      ),
    );
    expect(screen.getByTestId("enroll-qr")).toBeInTheDocument();
  });

  it("enrollment_step2_secret_tap_copies_to_clipboard", async () => {
    renderEnroll();
    const user = userEvent.setup();
    await user.click(screen.getByTestId("enroll-step1-continue"));
    await waitFor(() => screen.getByTestId("enroll-secret"));
    await user.click(screen.getByTestId("enroll-secret"));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      FAKE_ENROLL.secret_for_qr,
    );
  });

  it("enrollment_step3_confirm_success_shows_backup_codes", async () => {
    postTotpEnrollConfirmMock.mockResolvedValue(undefined);
    renderEnroll();
    const user = userEvent.setup();
    await user.click(screen.getByTestId("enroll-step1-continue"));
    await waitFor(() => screen.getByTestId("enroll-secret"));
    await user.click(screen.getByTestId("enroll-step2-continue"));
    await user.type(screen.getByTestId("totp-input"), "123456");
    await user.click(screen.getByTestId("enroll-step3-submit"));

    await waitFor(() =>
      expect(postTotpEnrollConfirmMock).toHaveBeenCalledWith(
        { code: "123456" },
        "fake-pre-totp-token",
      ),
    );
    await waitFor(() =>
      expect(screen.getByTestId("backup-codes-panel")).toBeInTheDocument(),
    );
    expect(screen.getAllByTestId("backup-code-item")).toHaveLength(10);
  });

  it("enrollment_step3_three_failures_restart_at_step2", async () => {
    postTotpEnrollConfirmMock.mockRejectedValue(
      new ApiError({
        status: 400,
        code: "identity.invalid_totp",
        message: "Invalid code.",
        details: null,
        requestId: "req-x",
      }),
    );
    renderEnroll();
    const user = userEvent.setup();
    await user.click(screen.getByTestId("enroll-step1-continue"));
    await waitFor(() => screen.getByTestId("enroll-secret"));
    await user.click(screen.getByTestId("enroll-step2-continue"));

    for (let i = 0; i < 3; i++) {
      await user.clear(screen.getByTestId("totp-input"));
      await user.type(screen.getByTestId("totp-input"), "000000");
      await user.click(screen.getByTestId("enroll-step3-submit"));
      await waitFor(() =>
        expect(postTotpEnrollConfirmMock).toHaveBeenCalledTimes(i + 1),
      );
    }

    await waitFor(() =>
      expect(screen.getByTestId("auth-enroll-step-2")).toBeInTheDocument(),
    );
    // The brief says the QR is re-fetched on restart (data set to null).
    await waitFor(() => expect(postTotpEnrollMock).toHaveBeenCalledTimes(2));
  });

  it("enrollment_step4_download_button_creates_blob", async () => {
    postTotpEnrollConfirmMock.mockResolvedValue(undefined);
    const createObjectURL = vi.fn().mockReturnValue("blob:fake");
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });

    renderEnroll();
    const user = userEvent.setup();
    await user.click(screen.getByTestId("enroll-step1-continue"));
    await waitFor(() => screen.getByTestId("enroll-secret"));
    await user.click(screen.getByTestId("enroll-step2-continue"));
    await user.type(screen.getByTestId("totp-input"), "123456");
    await user.click(screen.getByTestId("enroll-step3-submit"));
    await waitFor(() => screen.getByTestId("backup-codes-panel"));

    await user.click(screen.getByTestId("backup-download"));
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:fake");
  });
});
