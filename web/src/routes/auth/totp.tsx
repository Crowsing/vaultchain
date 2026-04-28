/**
 * `/auth/totp` — returning-user TOTP login challenge.
 *
 * AC-phase1-web-003-06: 6-digit input + "Use a backup code instead"
 * toggle. On `attempts_remaining` show the count. On 403
 * `identity.user_locked`, render the locked screen with a countdown
 * computed from `details.locked_until`.
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { AuthLayout } from "@/components/auth/AuthLayout";
import { TotpInput } from "@/components/auth/TotpInput";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-fetch";
import { postTotpVerify } from "@/features/auth/api";
import { useAuthStore } from "@/store/auth-store";

const BACKUP_CODE_RE = /[^A-Za-z0-9]/g;

type LockoutState = {
  lockedUntil: number;
  message: string;
};

function parseLockedUntil(details: unknown): number | null {
  if (typeof details !== "object" || details === null) return null;
  const lockedUntil = (details as Record<string, unknown>).locked_until;
  if (typeof lockedUntil !== "string") return null;
  const t = Date.parse(lockedUntil);
  return Number.isNaN(t) ? null : t;
}

function formatRemaining(ms: number): string {
  if (ms <= 0) return "0s";
  const total = Math.ceil(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  if (m === 0) return `${s}s`;
  return `${m}m ${s}s`;
}

export function TotpRoute(): React.JSX.Element {
  const navigate = useNavigate();
  const preTotpToken = useAuthStore((s) => s.preTotpToken);

  const [useBackup, setUseBackup] = useState(false);
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attemptsRemaining, setAttemptsRemaining] = useState<number | null>(
    null,
  );
  const [lockout, setLockout] = useState<LockoutState | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (lockout === null) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [lockout]);

  if (preTotpToken === null) {
    return (
      <AuthLayout
        testId="auth-totp-no-token"
        title="Session expired"
        subtitle="Request a new sign-in link to continue."
      >
        <Button onClick={() => navigate("/auth/login")}>Back to sign in</Button>
      </AuthLayout>
    );
  }

  if (lockout !== null) {
    const remaining = lockout.lockedUntil - now;
    return (
      <AuthLayout
        testId="auth-totp-locked"
        title="Account temporarily locked"
        subtitle="Too many failed attempts."
      >
        <p className="text-sm text-text-secondary">{lockout.message}</p>
        <p
          data-testid="totp-lockout-countdown"
          className="mt-4 text-sm text-text-primary"
          role="status"
          aria-live="polite"
        >
          Try again in <strong>{formatRemaining(remaining)}</strong>.
        </p>
        <Button
          variant="outline"
          className="mt-4"
          onClick={() => navigate("/auth/login")}
        >
          Back to sign in
        </Button>
      </AuthLayout>
    );
  }

  const minLength = useBackup ? 8 : 6;
  const maxLength = useBackup ? 12 : 6;
  const codeReady = useBackup
    ? code.replace(BACKUP_CODE_RE, "").length >= minLength
    : code.length >= 6;

  const handleSubmit = async (): Promise<void> => {
    setError(null);
    setSubmitting(true);
    try {
      const cleaned = useBackup
        ? code.replace(BACKUP_CODE_RE, "").toUpperCase()
        : code;
      const resp = await postTotpVerify(
        { code: cleaned, use_backup_code: useBackup },
        preTotpToken,
      );
      if (resp.success) {
        useAuthStore.getState().setPreTotpToken(null);
        navigate("/dashboard", { replace: true });
        return;
      }
      setError("Code did not match. Try again.");
      setAttemptsRemaining(
        typeof resp.attempts_remaining === "number"
          ? resp.attempts_remaining
          : null,
      );
      setCode("");
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 403 && e.code === "identity.user_locked") {
          const lockedUntil = parseLockedUntil(e.details);
          if (lockedUntil !== null) {
            setLockout({ lockedUntil, message: e.message });
            return;
          }
        }
        setError(e.message);
      } else {
        setError("Network error. Try again.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthLayout
      testId="auth-totp"
      title="Two-factor authentication"
      subtitle={
        useBackup
          ? "Enter one of your backup codes."
          : "Enter the six-digit code from your authenticator app."
      }
    >
      <div className="flex flex-col gap-4">
        {useBackup ? (
          <input
            data-testid="totp-backup-input"
            type="text"
            autoComplete="one-time-code"
            inputMode="text"
            spellCheck={false}
            maxLength={maxLength}
            value={code}
            disabled={submitting}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            placeholder="ABC1-DEF2"
            className="w-full rounded-md border border-border-default bg-bg-surface px-3 py-3 text-center font-mono text-lg tracking-[0.25em] text-text-primary focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand disabled:opacity-50"
            aria-label="Backup code"
          />
        ) : (
          <TotpInput value={code} onChange={setCode} disabled={submitting} />
        )}

        {error ? (
          <p data-testid="totp-error" className="text-xs text-danger">
            {error}
            {attemptsRemaining !== null ? (
              <>
                {" "}
                <span data-testid="totp-attempts">
                  {attemptsRemaining} attempt
                  {attemptsRemaining === 1 ? "" : "s"} remaining.
                </span>
              </>
            ) : null}
          </p>
        ) : null}

        <Button
          data-testid="totp-submit"
          onClick={() => void handleSubmit()}
          disabled={!codeReady || submitting}
        >
          {submitting ? "Verifying…" : "Sign in"}
        </Button>

        <button
          type="button"
          data-testid="totp-toggle-backup"
          onClick={() => {
            setUseBackup((v) => !v);
            setCode("");
            setError(null);
            setAttemptsRemaining(null);
          }}
          className="text-sm text-text-secondary underline-offset-2 hover:underline"
        >
          {useBackup
            ? "Use authenticator app instead"
            : "Use a backup code instead"}
        </button>
      </div>
    </AuthLayout>
  );
}
