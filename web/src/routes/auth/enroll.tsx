/**
 * `/auth/enroll` — TOTP enrollment 4-step wizard.
 *
 * AC-phase1-web-003-05:
 *   step 1 — explain + recommended apps
 *   step 2 — QR + manual base32 secret with tap-to-copy
 *   step 3 — 6-digit code submission
 *   step 4 — backup codes display
 *
 * Step 2 fires `POST /api/v1/auth/totp/enroll` once on entry to fetch
 * QR data; step 3 fires `POST /api/v1/auth/totp/enroll/confirm`. On 3
 * failures at step 3, the wizard restarts at step 2 (per state
 * machine).
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import QRCode from "qrcode";

import { AuthLayout } from "@/components/auth/AuthLayout";
import { BackupCodesPanel } from "@/components/auth/BackupCodesPanel";
import { TotpInput } from "@/components/auth/TotpInput";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { ApiError } from "@/lib/api-fetch";
import { postTotpEnroll, postTotpEnrollConfirm } from "@/features/auth/api";
import { useAuthStore } from "@/store/auth-store";

const RECOMMENDED_APPS = [
  "1Password",
  "Authy",
  "Google Authenticator",
  "Microsoft Authenticator",
];

const MAX_CONFIRM_FAILURES = 3;

type EnrollData = {
  secret_for_qr: string;
  qr_payload_uri: string;
  backup_codes: string[];
};

export function EnrollRoute(): React.JSX.Element {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const preTotpToken = useAuthStore((s) => s.preTotpToken);

  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);
  const [data, setData] = useState<EnrollData | null>(null);
  const [enrollError, setEnrollError] = useState<string | null>(null);
  const [code, setCode] = useState<string>("");
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [failureCount, setFailureCount] = useState<number>(0);
  const [submitting, setSubmitting] = useState(false);
  const [qrSvg, setQrSvg] = useState<string | null>(null);

  // Fetch QR data the first time we land on step 2.
  useEffect(() => {
    if (step !== 2 || data !== null || preTotpToken === null) return;
    let cancelled = false;
    void (async (): Promise<void> => {
      try {
        const resp = (await postTotpEnroll(preTotpToken)) as EnrollData;
        if (cancelled) return;
        setData(resp);
      } catch (e) {
        if (cancelled) return;
        setEnrollError(
          e instanceof ApiError
            ? e.message
            : "Could not start enrollment. Try again.",
        );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [step, data, preTotpToken]);

  useEffect(() => {
    if (data === null) {
      setQrSvg(null);
      return;
    }
    let cancelled = false;
    void QRCode.toString(data.qr_payload_uri, { type: "svg" }).then((svg) => {
      if (cancelled) return;
      setQrSvg(svg);
    });
    return () => {
      cancelled = true;
    };
  }, [data]);

  const stepLabel = useMemo(() => `Step ${step} of 4`, [step]);

  // The token is cleared the moment confirm succeeds (we're "logged in"
  // via cookies from then on), so once we're on step 4 we no longer
  // need it. Only the earlier steps require a live token.
  if (preTotpToken === null && step < 4) {
    return (
      <AuthLayout
        testId="auth-enroll-no-token"
        title="Session expired"
        subtitle="Request a new sign-in link to continue."
      >
        <Button onClick={() => navigate("/auth/signup")}>
          Back to sign up
        </Button>
      </AuthLayout>
    );
  }

  const handleConfirm = async (): Promise<void> => {
    if (preTotpToken === null) return;
    setConfirmError(null);
    setSubmitting(true);
    try {
      await postTotpEnrollConfirm({ code }, preTotpToken);
      useAuthStore.getState().setPreTotpToken(null);
      setStep(4);
    } catch (e) {
      const message =
        e instanceof ApiError ? e.message : "Verification failed.";
      setConfirmError(message);
      const next = failureCount + 1;
      setFailureCount(next);
      if (next >= MAX_CONFIRM_FAILURES) {
        showToast("Too many attempts. Re-scan the QR and try again.");
        setCode("");
        setData(null);
        setFailureCount(0);
        setStep(2);
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthLayout
      testId={`auth-enroll-step-${step}`}
      title="Set up two-factor authentication"
      subtitle={stepLabel}
    >
      {step === 1 ? (
        <div className="flex flex-col gap-4">
          <p className="text-sm text-text-secondary">
            Two-factor authentication adds a second proof of identity at sign-in
            using a six-digit code from an authenticator app on your phone.
          </p>
          <div>
            <p className="text-sm font-medium text-text-primary">
              Recommended apps
            </p>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-text-secondary">
              {RECOMMENDED_APPS.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          </div>
          <Button
            data-testid="enroll-step1-continue"
            onClick={() => setStep(2)}
          >
            I have an app — continue
          </Button>
        </div>
      ) : null}

      {step === 2 ? (
        <div className="flex flex-col items-center gap-4">
          {data === null ? (
            enrollError ? (
              <p
                data-testid="enroll-fetch-error"
                className="text-sm text-danger"
              >
                {enrollError}
              </p>
            ) : (
              <p
                role="status"
                aria-live="polite"
                className="text-sm text-text-secondary"
              >
                Generating your QR code…
              </p>
            )
          ) : (
            <>
              <div
                data-testid="enroll-qr"
                className="rounded-md bg-bg-surface-raised p-4"
                aria-label="QR code"
                dangerouslySetInnerHTML={{ __html: qrSvg ?? "" }}
              />
              <div className="flex w-full flex-col items-center gap-2">
                <p className="text-xs text-text-muted">
                  Or enter this secret manually:
                </p>
                <button
                  type="button"
                  data-testid="enroll-secret"
                  onClick={() => {
                    void navigator.clipboard?.writeText(data.secret_for_qr);
                    showToast("Secret copied to clipboard");
                  }}
                  className="rounded-md bg-bg-surface-sunken px-3 py-2 font-mono text-sm tracking-wider text-text-primary hover:bg-bg-surface-raised"
                >
                  {data.secret_for_qr}
                </button>
              </div>
              <Button
                data-testid="enroll-step2-continue"
                onClick={() => setStep(3)}
              >
                I scanned the QR — continue
              </Button>
            </>
          )}
        </div>
      ) : null}

      {step === 3 ? (
        <div className="flex flex-col gap-4">
          <p className="text-sm text-text-secondary">
            Enter the six-digit code from your authenticator app.
          </p>
          <TotpInput value={code} onChange={setCode} disabled={submitting} />
          {confirmError ? (
            <p
              data-testid="enroll-confirm-error"
              className="text-xs text-danger"
            >
              {confirmError}
            </p>
          ) : null}
          <Button
            data-testid="enroll-step3-submit"
            onClick={() => void handleConfirm()}
            disabled={code.length < 6 || submitting}
          >
            {submitting ? "Verifying…" : "Verify and continue"}
          </Button>
          <p className="text-xs text-text-muted">
            Attempts remaining before the wizard restarts:{" "}
            {MAX_CONFIRM_FAILURES - failureCount}
          </p>
        </div>
      ) : null}

      {step === 4 && data ? (
        <BackupCodesPanel
          codes={data.backup_codes}
          onAcknowledge={() => navigate("/dashboard", { replace: true })}
        />
      ) : null}
    </AuthLayout>
  );
}
