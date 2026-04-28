/**
 * Zustand auth store — ephemeral, NOT persisted to localStorage.
 *
 * The pre-TOTP token rides in `sessionStorage` (5-min backend TTL,
 * dies with the tab). The 30s resend cooldown is plain in-memory
 * because resetting on reload is acceptable per the brief.
 */
import { create } from "zustand";

const PRE_TOTP_KEY = "vc-pre-totp-token";

function readPreTotp(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(PRE_TOTP_KEY);
  } catch {
    return null;
  }
}

function writePreTotp(value: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (value === null) window.sessionStorage.removeItem(PRE_TOTP_KEY);
    else window.sessionStorage.setItem(PRE_TOTP_KEY, value);
  } catch {
    /* ignore */
  }
}

type AuthStore = {
  preTotpToken: string | null;
  setPreTotpToken: (token: string | null) => void;
  resendCooldownEndAt: number | null;
  startResendCooldown: (durationMs: number) => void;
};

export const useAuthStore = create<AuthStore>((set) => ({
  preTotpToken: readPreTotp(),
  setPreTotpToken: (token) => {
    writePreTotp(token);
    set({ preTotpToken: token });
  },
  resendCooldownEndAt: null,
  startResendCooldown: (durationMs) => {
    set({ resendCooldownEndAt: Date.now() + durationMs });
  },
}));

export const RESEND_COOLDOWN_MS = 30_000;
