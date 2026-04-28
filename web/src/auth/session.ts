/**
 * Session bootstrap + 401 event-bus.
 *
 * AC-phase1-web-005-01 calls `bootstrapSession` on cold load. The
 * function wraps `apiFetch("/api/v1/me")` with a 250ms minimum
 * splash duration to avoid flicker, then translates the result
 * into a Zustand `userStore` mutation + a navigation hint that the
 * shell consumes.
 *
 * AC-phase1-web-005-05 wires the global 401 interceptor: when a
 * mid-session request returns 401, `apiFetch` dispatches
 * `'session:expired'` on `sessionEvents`, which the shell's
 * top-level layout subscribes to and uses to navigate.
 */
import { ApiError, apiFetch } from "@/lib/api-fetch";
import { useUserStore, type AuthedUser } from "@/store/user-store";

import { sessionEvents } from "./session-events";

export { sessionEvents } from "./session-events";

const MIN_SPLASH_MS = 250;

/** Outcome the shell uses to decide where to render or navigate. */
export type SessionBootstrapOutcome =
  | { kind: "authenticated"; user: AuthedUser }
  | {
      kind: "redirect";
      to: "/auth/login" | "/auth/totp";
      redirectFrom?: string;
    }
  | { kind: "network-error"; error: ApiError };

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function fetchMe(): Promise<AuthedUser> {
  const me = (await apiFetch("/api/v1/me")) as AuthedUser;
  return me;
}

export async function bootstrapSession(opts?: {
  redirectFrom?: string;
}): Promise<SessionBootstrapOutcome> {
  useUserStore.getState().setStatus("loading");
  const [meResult] = await Promise.all([
    fetchMe()
      .then((user) => ({ ok: true as const, user }))
      .catch((error: unknown) => ({ ok: false as const, error })),
    sleep(MIN_SPLASH_MS),
  ]);

  if (meResult.ok) {
    useUserStore.getState().setUser(meResult.user);
    return { kind: "authenticated", user: meResult.user };
  }

  const error = meResult.error;
  if (error instanceof ApiError) {
    if (error.status === 401) {
      useUserStore.getState().clear();
      const target =
        error.code === "identity.totp_required" ? "/auth/totp" : "/auth/login";
      const out: SessionBootstrapOutcome = { kind: "redirect", to: target };
      if (opts?.redirectFrom !== undefined)
        out.redirectFrom = opts.redirectFrom;
      return out;
    }
    if (error.status >= 500 || error.status === 0) {
      useUserStore.getState().setStatus("error");
      return { kind: "network-error", error };
    }
    if (error.status === 403 && error.code === "identity.totp_required") {
      useUserStore.getState().clear();
      const out: SessionBootstrapOutcome = {
        kind: "redirect",
        to: "/auth/totp",
      };
      if (opts?.redirectFrom !== undefined)
        out.redirectFrom = opts.redirectFrom;
      return out;
    }
  }

  useUserStore.getState().setStatus("error");
  if (error instanceof ApiError) {
    return { kind: "network-error", error };
  }
  // Unknown error type — wrap so the caller has a uniform shape.
  return {
    kind: "network-error",
    error: new ApiError({
      status: 0,
      code: "shared.unknown",
      message: error instanceof Error ? error.message : "Unknown error",
      details: null,
      requestId: "",
    }),
  };
}

export function dispatchSessionExpired(detail: {
  code: string;
  status: number;
}): void {
  sessionEvents.dispatchEvent(new CustomEvent("session:expired", { detail }));
}

/** Subscribe to the global `session:expired` event. Returns the
 *  unsubscribe function. The shell layout uses this to navigate to
 *  `/auth/login` whenever a mid-session 401 fires. */
export function onSessionExpired(
  handler: (detail: { code: string; status: number }) => void,
): () => void {
  const listener = (ev: Event): void => {
    const ce = ev as CustomEvent<{ code: string; status: number }>;
    handler(ce.detail);
  };
  sessionEvents.addEventListener("session:expired", listener);
  return () => {
    sessionEvents.removeEventListener("session:expired", listener);
  };
}
