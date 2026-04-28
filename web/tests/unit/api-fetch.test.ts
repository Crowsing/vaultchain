// Unit tests for the `apiFetch` wrapper, `ApiError` class,
// idempotency-key persistence, and the TanStack Query retry policy.
//
// Mapping to acceptance criteria:
//   - AC-phase1-web-002-02 → apifetch_includes_credentials_and_csrf,
//                            apifetch_generates_and_persists_idempotency_key
//   - AC-phase1-web-002-03 → apifetch_parses_error_envelope_into_apierror
//   - AC-phase1-web-002-05 → apifetch_reuses_key_on_retry,
//                            apifetch_evicts_key_on_terminal_response,
//                            apifetch_evicts_key_on_4xx
//   - AC-phase1-web-002-06 → query_client_retry_policy_for_apierror

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clear } from "idb-keyval";

import { ApiError, apiFetch } from "@/lib/api-fetch";
import { peekIdempotencyKey } from "@/lib/idempotency";
import { buildQueryClient } from "@/lib/query-client";

const ENV_API_BASE = "http://localhost:8000";

type FetchInit = RequestInit & { headers?: Record<string, string> };
type FetchCall = { url: string; init: FetchInit };

function setCookie(name: string, value: string): void {
  document.cookie = `${name}=${value}; path=/`;
}

function clearCookies(): void {
  for (const c of document.cookie.split(";")) {
    const eq = c.indexOf("=");
    const name = (eq > -1 ? c.slice(0, eq) : c).trim();
    if (name)
      document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
  }
}

function jsonResponse(
  status: number,
  body: unknown,
  init?: ResponseInit,
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
    ...init,
  });
}

beforeEach(async () => {
  await clear();
  clearCookies();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("apiFetch", () => {
  it("apifetch_includes_credentials_and_csrf", async () => {
    setCookie("csrf", "csrf-token-xyz");
    const calls: FetchCall[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ url: String(input), init: (init ?? {}) as FetchInit });
        return jsonResponse(202, { message_sent: true });
      }),
    );

    await apiFetch("/api/v1/auth/request", {
      method: "POST",
      body: { email: "alice@example.com", mode: "signup" },
    });

    expect(calls).toHaveLength(1);
    const call = calls[0]!;
    expect(call.url).toBe(`${ENV_API_BASE}/api/v1/auth/request`);
    expect(call.init.credentials).toBe("include");
    expect(call.init.method).toBe("POST");
    const headers = call.init.headers ?? {};
    expect(headers["Accept"]).toBe("application/json");
    expect(headers["Content-Type"]).toBe("application/json");
    expect(headers["X-CSRF-Token"]).toBe("csrf-token-xyz");
    expect(headers["Idempotency-Key"]).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
    );
  });

  it("apifetch_skips_csrf_and_idempotency_on_get", async () => {
    setCookie("csrf", "csrf-token-xyz");
    const calls: FetchCall[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ url: String(input), init: (init ?? {}) as FetchInit });
        return jsonResponse(200, {
          id: "id",
          email: "a@example.com",
          status: "verified",
          kyc_tier: 0,
          totp_enrolled: true,
          created_at: "2026-04-28T09:00:00Z",
        });
      }),
    );

    await apiFetch("/api/v1/me");

    const headers = calls[0]!.init.headers ?? {};
    expect(headers["X-CSRF-Token"]).toBeUndefined();
    expect(headers["Idempotency-Key"]).toBeUndefined();
    expect(calls[0]!.init.credentials).toBe("include");
  });

  it("apifetch_generates_and_persists_idempotency_key", async () => {
    const calls: FetchCall[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ url: String(input), init: (init ?? {}) as FetchInit });
        // simulate the request hanging — return a never-resolving promise
        // is overkill; just return 5xx so the wrapper marks the record
        // unresolved and we can assert on storage afterwards.
        return jsonResponse(503, {
          error: {
            code: "shared.upstream",
            message: "down",
            details: null,
            request_id: "rid",
          },
        });
      }),
    );

    const body = { email: "alice@example.com", mode: "signup" } as const;
    await expect(
      apiFetch("/api/v1/auth/request", { method: "POST", body }),
    ).rejects.toBeInstanceOf(ApiError);

    const stored = await peekIdempotencyKey({
      method: "POST",
      path: "/api/v1/auth/request",
      body,
    });
    expect(stored).toBeDefined();
    expect(stored!.key).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
    );
    expect(stored!.resolved).toBe(false);
    expect(calls[0]!.init.headers!["Idempotency-Key"]).toBe(stored!.key);
  });

  it("apifetch_reuses_key_on_retry", async () => {
    const sentKeys: string[] = [];
    let fetchCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        const i = (init ?? {}) as FetchInit;
        sentKeys.push(i.headers!["Idempotency-Key"]!);
        fetchCount += 1;
        if (fetchCount === 1) {
          return jsonResponse(503, {
            error: {
              code: "shared.upstream",
              message: "x",
              details: null,
              request_id: "r1",
            },
          });
        }
        return jsonResponse(202, { message_sent: true });
      }),
    );

    const body = { email: "alice@example.com", mode: "signup" } as const;
    await expect(
      apiFetch("/api/v1/auth/request", { method: "POST", body }),
    ).rejects.toBeInstanceOf(ApiError);
    await apiFetch("/api/v1/auth/request", { method: "POST", body });

    expect(sentKeys).toHaveLength(2);
    expect(sentKeys[0]).toBe(sentKeys[1]);
  });

  it("apifetch_evicts_key_on_terminal_response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(202, { message_sent: true })),
    );

    const body = { email: "alice@example.com", mode: "signup" } as const;
    await apiFetch("/api/v1/auth/request", { method: "POST", body });

    const stored = await peekIdempotencyKey({
      method: "POST",
      path: "/api/v1/auth/request",
      body,
    });
    expect(stored).toBeUndefined();
  });

  it("apifetch_evicts_key_on_4xx", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(422, {
          error: {
            code: "shared.validation_error",
            message: "bad",
            details: null,
            request_id: "rid-422",
          },
        }),
      ),
    );

    const body = { email: "alice@example.com", mode: "signup" } as const;
    await expect(
      apiFetch("/api/v1/auth/request", { method: "POST", body }),
    ).rejects.toBeInstanceOf(ApiError);

    const stored = await peekIdempotencyKey({
      method: "POST",
      path: "/api/v1/auth/request",
      body,
    });
    expect(stored).toBeUndefined();
  });

  it("apifetch_parses_error_envelope_into_apierror", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(401, {
          error: {
            code: "identity.unauthenticated",
            message: "Please sign in",
            details: { reason: "no_session" },
            request_id: "req-abc-123",
          },
        }),
      ),
    );

    const error = await apiFetch("/api/v1/me").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toBeInstanceOf(Error);
    const ae = error as ApiError;
    expect(ae.status).toBe(401);
    expect(ae.code).toBe("identity.unauthenticated");
    expect(ae.message).toBe("Please sign in");
    expect(ae.requestId).toBe("req-abc-123");
    expect(ae.details).toEqual({ reason: "no_session" });
  });

  it("apifetch_falls_back_to_generic_apierror_for_non_envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("upstream broken", { status: 502 })),
    );

    const error = await apiFetch("/api/v1/me").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    const ae = error as ApiError;
    expect(ae.status).toBe(502);
    expect(ae.code).toBe("shared.unknown");
  });
});

describe("buildQueryClient", () => {
  it("query_client_retry_policy_for_apierror", () => {
    const qc = buildQueryClient();
    const opts = qc.getDefaultOptions();
    const retry = opts.queries?.retry;
    expect(typeof retry).toBe("function");
    const fn = retry as (count: number, error: unknown) => boolean;

    const networkErr = new Error("network down");
    expect(fn(0, networkErr)).toBe(true);
    expect(fn(1, networkErr)).toBe(true);
    expect(fn(2, networkErr)).toBe(false);

    const validation = new ApiError({
      status: 422,
      code: "shared.validation_error",
      message: "bad",
      details: null,
      requestId: "x",
    });
    expect(fn(0, validation)).toBe(false);

    const upstream = new ApiError({
      status: 502,
      code: "shared.upstream",
      message: "x",
      details: null,
      requestId: "y",
    });
    expect(fn(0, upstream)).toBe(true);

    expect(opts.queries?.staleTime).toBe(30_000);
  });
});
