import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { adminApiFetch } from "@/auth/apiFetch";
import { ApiError } from "@/auth/types";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("adminApiFetch", () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    fetchSpy = vi.spyOn(globalThis, "fetch") as never;
    document.cookie = "admin_csrf=test-csrf; path=/";
  });
  afterEach(() => {
    vi.restoreAllMocks();
    document.cookie =
      "admin_csrf=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("calls /admin/api/v1/<path> with credentials: include", async () => {
    fetchSpy.mockResolvedValueOnce(jsonResponse(200, { ok: true }));
    await adminApiFetch("/auth/me", { method: "GET" });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0]!;
    expect(url).toBe("/admin/api/v1/auth/me");
    expect((init as RequestInit).credentials).toBe("include");
  });

  it("attaches X-CSRF-Token + X-Idempotency-Key on POST", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse(200, { pre_totp_required: true }),
    );
    await adminApiFetch("/auth/login", {
      method: "POST",
      body: { email: "a@b.c", password: "secret" },
    });

    const [, init] = fetchSpy.mock.calls[0]!;
    const headers = new Headers((init as RequestInit).headers);
    expect(headers.get("X-CSRF-Token")).toBe("test-csrf");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("X-Idempotency-Key")).toBeTruthy();
  });

  it("does NOT attach X-Idempotency-Key on GET", async () => {
    fetchSpy.mockResolvedValueOnce(jsonResponse(200, {}));
    await adminApiFetch("/auth/me", { method: "GET" });

    const [, init] = fetchSpy.mock.calls[0]!;
    const headers = new Headers((init as RequestInit).headers);
    expect(headers.has("X-Idempotency-Key")).toBe(false);
  });

  it("throws ApiError parsed from envelope on 4xx", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse(401, {
        error: {
          code: "identity.invalid_credentials",
          message: "Bad credentials.",
          details: { reason: "totp_failed" },
          request_id: "req_X",
          documentation_url:
            "https://example.test/identity.invalid_credentials",
        },
      }),
    );

    await expect(
      adminApiFetch("/auth/login", { method: "POST", body: {} }),
    ).rejects.toMatchObject({
      status: 401,
      code: "identity.invalid_credentials",
    });
  });

  it("returns undefined on 204 No Content", async () => {
    fetchSpy.mockResolvedValueOnce(new Response(null, { status: 204 }));
    const result = await adminApiFetch("/auth/logout", { method: "POST" });
    expect(result).toBeUndefined();
  });

  it("falls back to internal.unexpected when error body is not an envelope", async () => {
    fetchSpy.mockResolvedValueOnce(new Response("oops", { status: 500 }));
    await expect(
      adminApiFetch("/auth/me", { method: "GET" }),
    ).rejects.toBeInstanceOf(ApiError);
  });
});
