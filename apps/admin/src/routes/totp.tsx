import { useEffect, useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";

import { AdminShellEmpty } from "@/components/admin-shell";
import { adminTotpVerify } from "@/auth/api";
import { hasAdminPreTotpCookie } from "@/auth/csrf";
import { ApiError } from "@/auth/types";

const CODE_REGEX = /^[0-9]{6}$/;

function formatLockedMessage(
  details: Record<string, unknown> | undefined,
): string {
  const lockedUntil = details?.["locked_until"];
  if (typeof lockedUntil === "string" && lockedUntil) {
    return `Account locked until ${lockedUntil}`;
  }
  return "Account locked. Try again later.";
}

export default function TotpRoute() {
  const navigate = useNavigate();
  const [hasCookie, setHasCookie] = useState<boolean | null>(null);
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setHasCookie(hasAdminPreTotpCookie());
  }, []);

  if (hasCookie === false) {
    return (
      <Navigate
        to="/login"
        replace
        state={{ lockedMessage: "Please sign in again." }}
      />
    );
  }

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (!CODE_REGEX.test(code)) {
      setError("Enter the 6-digit code.");
      return;
    }

    setSubmitting(true);
    try {
      await adminTotpVerify({ code });
      navigate("/dashboard");
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "identity.user_locked") {
          navigate("/login", {
            replace: true,
            state: { lockedMessage: formatLockedMessage(err.details) },
          });
          return;
        }
        if (
          err.code === "identity.totp_invalid" ||
          err.code === "identity.invalid_credentials"
        ) {
          setCode("");
          setError("That code didn't work. Try again.");
        } else if (err.code === "identity.pre_totp_token_invalid") {
          navigate("/login", {
            replace: true,
            state: { lockedMessage: "Please sign in again." },
          });
          return;
        } else {
          setError(err.message || "Something went wrong, try again.");
        }
      } else {
        setError("Something went wrong, try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AdminShellEmpty>
      <div className="card" style={{ padding: "32px", textAlign: "center" }}>
        <h1
          className="text-xl font-semibold mb-1"
          style={{ color: "var(--text-primary)" }}
        >
          Two-factor code
        </h1>
        <p className="text-sm mb-6" style={{ color: "var(--text-secondary)" }}>
          Enter the 6-digit code from your authenticator app.
        </p>

        <form
          className="stack gap-3"
          style={{ textAlign: "left" }}
          onSubmit={onSubmit}
          noValidate
        >
          <div>
            <label className="input-label" htmlFor="admin-totp">
              Code
            </label>
            <input
              id="admin-totp"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              className="input"
              value={code}
              onChange={(e) =>
                setCode(e.target.value.replace(/\D/g, "").slice(0, 6))
              }
              maxLength={6}
              required
              aria-invalid={error != null}
              aria-describedby={error ? "admin-totp-error" : undefined}
              disabled={submitting}
            />
            {error && (
              <p
                id="admin-totp-error"
                role="alert"
                data-testid="admin-totp-error"
                className="text-sm"
                style={{ color: "var(--danger)", marginTop: "4px" }}
              >
                {error}
              </p>
            )}
          </div>
          <button
            type="submit"
            className="btn btn-primary btn-md"
            disabled={submitting}
            aria-busy={submitting}
          >
            {submitting ? "Verifying…" : "Verify"}
          </button>
        </form>
      </div>
    </AdminShellEmpty>
  );
}
