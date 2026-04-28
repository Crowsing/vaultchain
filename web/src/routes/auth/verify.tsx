/**
 * `/auth/verify` — magic-link landing.
 *
 * AC-phase1-web-003-04: validates the token, persists the
 * pre-TOTP token in sessionStorage via the auth store, and
 * navigates to /auth/enroll (first-time) or /auth/totp (returning).
 * On expired/used/invalid, shows an error state with "Request a
 * new link" CTA back to signup or login.
 */
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { AuthLayout } from "@/components/auth/AuthLayout";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-fetch";
import { postAuthVerify } from "@/features/auth/api";
import { useAuthStore } from "@/store/auth-store";

const MIN_VALIDATING_MS = 250;

type VerifyState =
  | { kind: "validating" }
  | { kind: "error"; code: string; message: string };

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function VerifyRoute(): React.JSX.Element {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const mode = (params.get("mode") ?? "signup") as "signup" | "login";
  const [state, setState] = useState<VerifyState>({ kind: "validating" });
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    void (async (): Promise<void> => {
      try {
        const [resp] = await Promise.all([
          postAuthVerify({ token, mode }),
          sleep(MIN_VALIDATING_MS),
        ]);
        useAuthStore.getState().setPreTotpToken(resp.pre_totp_token);
        if (resp.requires_totp_enrollment) {
          navigate("/auth/enroll", { replace: true });
        } else {
          navigate("/auth/totp", { replace: true });
        }
      } catch (e) {
        if (e instanceof ApiError) {
          setState({ kind: "error", code: e.code, message: e.message });
        } else {
          setState({
            kind: "error",
            code: "shared.network_error",
            message: "Network error. Try the link again.",
          });
        }
      }
    })();
  }, [token, mode, navigate]);

  if (state.kind === "validating") {
    return (
      <AuthLayout testId="auth-verify-validating">
        <div
          role="status"
          aria-live="polite"
          className="flex flex-col items-center gap-3 py-6 text-text-secondary"
        >
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-text-muted border-t-brand" />
          <p className="text-sm">Validating link…</p>
        </div>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout testId="auth-verify-error" title="Link not valid">
      <p className="text-sm text-text-secondary">{state.message}</p>
      <Button
        data-testid="verify-request-new"
        className="mt-4 w-full"
        onClick={() =>
          navigate(mode === "login" ? "/auth/login" : "/auth/signup")
        }
      >
        Request a new link
      </Button>
    </AuthLayout>
  );
}
