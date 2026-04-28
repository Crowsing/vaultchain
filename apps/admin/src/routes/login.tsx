import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { AdminShellEmpty } from "@/components/admin-shell";
import { adminLogin } from "@/auth/api";
import { ApiError } from "@/auth/types";

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type LocationState = {
  lockedMessage?: string;
};

function formatLockedMessage(
  details: Record<string, unknown> | undefined,
): string {
  const lockedUntil = details?.["locked_until"];
  if (typeof lockedUntil === "string" && lockedUntil) {
    return `Account locked until ${lockedUntil}`;
  }
  return "Account locked. Try again later.";
}

export default function LoginRoute() {
  const navigate = useNavigate();
  const location = useLocation();
  const stateMessage =
    (location.state as LocationState | null)?.lockedMessage ?? null;

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(stateMessage);
  const [emailError, setEmailError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);

    const trimmedEmail = email.trim();
    if (!EMAIL_REGEX.test(trimmedEmail)) {
      setEmailError("Enter a valid email address.");
      return;
    }
    setEmailError(null);

    setSubmitting(true);
    try {
      await adminLogin({ email: trimmedEmail, password });
      navigate("/totp");
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "identity.invalid_credentials") {
          setError("Email or password is incorrect.");
        } else if (err.code === "identity.user_locked") {
          setError(formatLockedMessage(err.details));
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
          VaultChain Admin
        </h1>
        <p className="text-sm mb-6" style={{ color: "var(--text-secondary)" }}>
          Sign in to continue.
        </p>

        <form
          className="stack gap-3"
          style={{ textAlign: "left" }}
          onSubmit={onSubmit}
          noValidate
        >
          <div>
            <label className="input-label" htmlFor="admin-email">
              Email
            </label>
            <input
              id="admin-email"
              type="email"
              autoComplete="username"
              className="input"
              placeholder="admin@vaultchain.example"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              aria-invalid={emailError != null}
              aria-describedby={emailError ? "admin-email-error" : undefined}
              disabled={submitting}
            />
            {emailError && (
              <p
                id="admin-email-error"
                role="alert"
                className="text-sm"
                style={{ color: "var(--danger)", marginTop: "4px" }}
              >
                {emailError}
              </p>
            )}
          </div>
          <div>
            <label className="input-label" htmlFor="admin-password">
              Password
            </label>
            <input
              id="admin-password"
              type="password"
              autoComplete="current-password"
              className="input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              aria-describedby={error ? "admin-password-error" : undefined}
              disabled={submitting}
            />
            {error && (
              <p
                id="admin-password-error"
                role="alert"
                data-testid="admin-login-error"
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
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="muted" style={{ fontSize: "12px", marginTop: "20px" }}>
          Admin access · audited · all actions logged.
        </p>
      </div>
    </AdminShellEmpty>
  );
}
