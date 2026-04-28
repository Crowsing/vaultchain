/**
 * "Resend link" button with a 30s cooldown after each send.
 *
 * AC-phase1-web-003-03: countdown timer client-side, in-memory only
 * (a reload resets it — acceptable). The cooldown end-time lives in
 * the auth store so multiple components (button + label) can read
 * the same value.
 */
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { RESEND_COOLDOWN_MS, useAuthStore } from "@/store/auth-store";

export function ResendCountdown({
  onResend,
  disabled,
}: {
  onResend: () => void | Promise<void>;
  disabled?: boolean;
}): React.JSX.Element {
  const endAt = useAuthStore((s) => s.resendCooldownEndAt);
  const [now, setNow] = useState<number>(() => Date.now());

  useEffect(() => {
    if (endAt === null) return;
    const handle = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(handle);
  }, [endAt]);

  const remainingMs = endAt === null ? 0 : Math.max(0, endAt - now);
  const cooling = remainingMs > 0;
  const seconds = Math.ceil(remainingMs / 1000);

  return (
    <Button
      type="button"
      data-testid="resend-button"
      variant="outline"
      disabled={disabled || cooling}
      onClick={() => {
        useAuthStore.getState().startResendCooldown(RESEND_COOLDOWN_MS);
        void onResend();
      }}
    >
      {cooling ? `Resend in ${seconds}s` : "Resend link"}
    </Button>
  );
}
