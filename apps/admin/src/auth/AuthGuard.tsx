import { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { adminMe } from "./api";
import { useAdminAuthStore } from "./store";
import { ApiError } from "./types";

const PUBLIC_PATHS = new Set(["/login", "/totp"]);
const SPLASH_MIN_MS = 250;

type AuthGuardProps = {
  children: React.ReactNode;
};

export function AuthGuard({ children }: AuthGuardProps) {
  const location = useLocation();
  const { user, bootstrapped, setUser, markBootstrapped, clear } =
    useAdminAuthStore();
  const [error, setError] = useState<unknown>(null);
  const [splashElapsed, setSplashElapsed] = useState(false);

  useEffect(() => {
    if (bootstrapped) {
      setSplashElapsed(true);
      return;
    }
    let cancelled = false;
    const start = Date.now();
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
        if (cancelled) return;
        const elapsed = Date.now() - start;
        const wait = Math.max(0, SPLASH_MIN_MS - elapsed);
        const finalize = () => {
          if (cancelled) return;
          markBootstrapped();
          setSplashElapsed(true);
        };
        if (wait === 0) finalize();
        else setTimeout(finalize, wait);
      });
    return () => {
      cancelled = true;
    };
  }, [bootstrapped, setUser, markBootstrapped, clear]);

  const isPublic = PUBLIC_PATHS.has(location.pathname);

  if (!bootstrapped || !splashElapsed) {
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
    const redirectTarget =
      location.pathname + (location.search || "") + (location.hash || "");
    const params = new URLSearchParams();
    if (redirectTarget && redirectTarget !== "/login") {
      params.set("redirect", redirectTarget);
    }
    const search = params.toString();
    return <Navigate to={search ? `/login?${search}` : "/login"} replace />;
  }

  return <>{children}</>;
}
