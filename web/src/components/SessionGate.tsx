/**
 * Top-level guard: runs `bootstrapSession` on mount, renders the
 * "Validating session…" splash while in flight, navigates on
 * outcome, and subscribes to `session:expired` for mid-session
 * 401s.
 *
 * AC-phase1-web-005-01: bootstrap is the gate before any authed
 * route renders.
 * AC-phase1-web-005-05: subscribes to the global event bus and
 * navigates to `/auth/login?redirect=<currentPath>` when fired.
 * AC-phase1-web-005-07: re-runs bootstrap silently on
 * `visibilitychange → visible`.
 */
import { useEffect, useRef, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { onSessionExpired, bootstrapSession } from "@/auth/session";
import type { SessionBootstrapOutcome } from "@/auth/session";
import { useUserStore } from "@/store/user-store";

type GateState =
  | { kind: "loading" }
  | { kind: "ready" }
  | { kind: "network-error"; message: string };

export function SessionGate(): React.JSX.Element {
  const navigate = useNavigate();
  const location = useLocation();
  const status = useUserStore((s) => s.status);
  const [state, setState] = useState<GateState>({ kind: "loading" });
  const lastRunRef = useRef<number>(0);

  const run = useRef<(opts?: { silent?: boolean }) => Promise<void>>(
    async () => {},
  );
  run.current = async (opts) => {
    const isSilent = opts?.silent === true;
    if (!isSilent) setState({ kind: "loading" });
    lastRunRef.current = Date.now();
    const outcome: SessionBootstrapOutcome = await bootstrapSession({
      redirectFrom: location.pathname + location.search,
    });
    switch (outcome.kind) {
      case "authenticated":
        setState({ kind: "ready" });
        return;
      case "redirect": {
        const redirect = encodeURIComponent(
          location.pathname + location.search,
        );
        navigate(`${outcome.to}?redirect=${redirect}`, { replace: true });
        return;
      }
      case "network-error":
        if (!isSilent) {
          setState({
            kind: "network-error",
            message: outcome.error.message || "Network error",
          });
        }
        return;
    }
  };

  useEffect(() => {
    void run.current();
  }, []);

  // AC-phase1-web-005-05 — subscribe to mid-session 401.
  useEffect(() => {
    return onSessionExpired((detail) => {
      useUserStore.getState().clear();
      const target =
        detail.code === "identity.totp_required" ? "/auth/totp" : "/auth/login";
      const redirect = encodeURIComponent(location.pathname + location.search);
      navigate(`${target}?redirect=${redirect}`, { replace: true });
    });
  }, [navigate, location.pathname, location.search]);

  // AC-phase1-web-005-07 — silent re-validation when the tab regains focus.
  useEffect(() => {
    if (typeof document === "undefined") return;
    const handler = (): void => {
      if (document.visibilityState !== "visible") return;
      if (status !== "authenticated") return;
      void run.current({ silent: true });
    };
    document.addEventListener("visibilitychange", handler);
    return () => {
      document.removeEventListener("visibilitychange", handler);
    };
  }, [status]);

  if (state.kind === "loading") {
    return (
      <div
        role="status"
        aria-live="polite"
        data-testid="session-splash"
        className="flex h-screen flex-col items-center justify-center gap-3 bg-bg-page text-text-secondary"
      >
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-text-muted border-t-brand" />
        <p className="text-sm">Validating session…</p>
      </div>
    );
  }
  if (state.kind === "network-error") {
    return (
      <div
        role="alert"
        data-testid="session-network-error"
        className="flex h-screen flex-col items-center justify-center gap-4 bg-bg-page p-8 text-center text-text-primary"
      >
        <h2 className="text-xl font-semibold">Connection problem</h2>
        <p className="max-w-md text-sm text-text-secondary">{state.message}</p>
        <Button onClick={() => void run.current()}>Retry</Button>
      </div>
    );
  }
  return <Outlet />;
}
