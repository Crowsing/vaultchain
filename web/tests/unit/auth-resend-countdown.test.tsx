// Covers AC-phase1-web-003-03: resend cooldown decrements, button is
// disabled while cooling, and re-enables after the window elapses.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";

import { ResendCountdown } from "@/components/auth/ResendCountdown";
import { RESEND_COOLDOWN_MS, useAuthStore } from "@/store/auth-store";

beforeEach(() => {
  vi.useFakeTimers();
  useAuthStore.setState({ resendCooldownEndAt: null });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("ResendCountdown", () => {
  it("resend_disabled_while_cooling", () => {
    useAuthStore.setState({ resendCooldownEndAt: Date.now() + 30_000 });
    render(<ResendCountdown onResend={() => Promise.resolve()} />);
    const button = screen.getByTestId("resend-button");
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent(/Resend in/i);
  });

  it("resend_button_re_enables_after_cooldown", () => {
    useAuthStore.setState({ resendCooldownEndAt: Date.now() + 1_000 });
    render(<ResendCountdown onResend={() => Promise.resolve()} />);
    expect(screen.getByTestId("resend-button")).toBeDisabled();
    act(() => {
      vi.advanceTimersByTime(1_500);
    });
    expect(screen.getByTestId("resend-button")).not.toBeDisabled();
  });

  it("resend_click_starts_new_cooldown", async () => {
    const onResend = vi.fn().mockResolvedValue(undefined);
    render(<ResendCountdown onResend={onResend} />);
    const button = screen.getByTestId("resend-button");
    expect(button).not.toBeDisabled();
    await act(async () => {
      button.click();
      await Promise.resolve();
    });
    expect(onResend).toHaveBeenCalledTimes(1);
    const endAt = useAuthStore.getState().resendCooldownEndAt;
    expect(endAt).not.toBeNull();
    expect((endAt ?? 0) - Date.now()).toBeGreaterThan(
      RESEND_COOLDOWN_MS - 1_000,
    );
  });
});
