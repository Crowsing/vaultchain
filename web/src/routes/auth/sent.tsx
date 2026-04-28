/**
 * `/auth/sent` — "Check your email" landing.
 *
 * AC-phase1-web-003-03: shows the email passed via query param,
 * "Resend link" with 30s cooldown, "Use a different email" link, and
 * an open-by-default "Link sent, but not received?" hint.
 */
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { AuthLayout } from "@/components/auth/AuthLayout";
import { ResendCountdown } from "@/components/auth/ResendCountdown";
import { ApiError } from "@/lib/api-fetch";
import { postAuthRequest } from "@/features/auth/api";
import { RESEND_COOLDOWN_MS, useAuthStore } from "@/store/auth-store";

export function SentRoute(): React.JSX.Element {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const email = params.get("email") ?? "";
  const mode = (params.get("mode") ?? "signup") as "signup" | "login";
  const [resendError, setResendError] = useState<string | null>(null);

  // Start the cooldown on mount — the user just arrived from a successful
  // request, so the resend should be disabled for 30s by default.
  useEffect(() => {
    if (useAuthStore.getState().resendCooldownEndAt === null) {
      useAuthStore.getState().startResendCooldown(RESEND_COOLDOWN_MS);
    }
  }, []);

  const handleResend = async (): Promise<void> => {
    setResendError(null);
    try {
      await postAuthRequest({ email, mode });
    } catch (e) {
      setResendError(
        e instanceof ApiError ? e.message : "Could not resend. Try again.",
      );
    }
  };

  return (
    <AuthLayout testId="auth-sent" title="Check your email">
      <p className="text-sm text-text-secondary">
        We sent a sign-in link to{" "}
        <strong className="text-text-primary">{email}</strong>. Open it on this
        device to continue.
      </p>

      <div className="mt-6 flex flex-col gap-3">
        <ResendCountdown onResend={handleResend} />
        <button
          type="button"
          data-testid="sent-different-email"
          onClick={() =>
            navigate(mode === "signup" ? "/auth/signup" : "/auth/login")
          }
          className="text-sm text-text-secondary underline-offset-2 hover:underline"
        >
          Use a different email
        </button>
      </div>

      {resendError ? (
        <p data-testid="sent-resend-error" className="mt-3 text-xs text-danger">
          {resendError}
        </p>
      ) : null}

      <details
        data-testid="sent-help"
        open
        className="mt-6 rounded-md bg-bg-surface-sunken p-3 text-sm text-text-secondary"
      >
        <summary className="cursor-pointer font-medium text-text-primary">
          Link sent, but not received?
        </summary>
        <ul className="mt-2 list-disc space-y-1 pl-4">
          <li>Check the spam / promotions folder.</li>
          <li>Confirm the email is typed correctly above.</li>
          <li>Wait 30 seconds and tap "Resend link".</li>
          <li>
            Still nothing?{" "}
            <a
              href="/docs/account-recovery"
              className="underline-offset-2 hover:underline"
            >
              Recover your account
            </a>
            .
          </li>
        </ul>
      </details>
    </AuthLayout>
  );
}
