import { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { adminMe } from "./api";
import { useAdminAuthStore } from "./store";
import { ApiError } from "./types";

const PUBLIC_PATHS = new Set(["/login", "/totp"]);

type AuthGuardProps = {
  children: React.ReactNode;
};

export function AuthGuard({ children }: AuthGuardProps) {
  const location = useLocation();
  const { user, bootstrapped, setUser, markBootstrapped, clear } =
    useAdminAuthStore();
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (bootstrapped) return;
    let cancelled = false;
    void adminMe()
      .then((u) => {
        if (!cancelled) setUser(u);
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 401) {
          clear();
          return;
        }
        setError(e);
      })
      .finally(() => {
        if (!cancelled) markBootstrapped();
      });
    return () => {
      cancelled = true;
    };
  }, [bootstrapped, setUser, markBootstrapped, clear]);

  const isPublic = PUBLIC_PATHS.has(location.pathname);

  if (!bootstrapped) {
    return (
      <div
        data-testid="auth-guard-loading"
        className="min-h-screen flex items-center justify-center"
      >
        <p className="muted text-sm" style={{ color: "var(--text-secondary)" }}>
          Loading…
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div
        data-testid="auth-guard-error"
        className="min-h-screen flex items-center justify-center"
      >
        <p className="muted text-sm" style={{ color: "var(--danger)" }}>
          Could not load admin session. Refresh to try again.
        </p>
      </div>
    );
  }

  if (!user && !isPublic) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return <>{children}</>;
}
