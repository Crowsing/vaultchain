/**
 * Typed `fetch` wrapper for VaultChain HTTP endpoints.
 *
 * Behaviour summary (per AC-phase1-web-002-02..05):
 *   • `credentials: "include"` so the session cookie ride-alongs.
 *   • Reads the `csrf` cookie and sends it as `X-CSRF-Token` on
 *     mutating verbs.
 *   • Generates and persists an `Idempotency-Key` (UUIDv4) per
 *     `(method, path, stable-body-hash)` for mutating verbs.
 *   • Reuses the persisted key on retries; evicts it on any terminal
 *     2xx or 4xx response.
 *   • Throws `ApiError` carrying the parsed `{code, message, details,
 *     request_id}` envelope.
 */

import type { paths } from "@vaultchain/shared-types";

import { ApiError } from "./api-error";
import {
  evictIdempotencyKey,
  getOrCreateIdempotencyKey,
  type RequestDescriptor,
} from "./idempotency";

export { ApiError } from "./api-error";

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
const MUTATING: ReadonlySet<Method> = new Set([
  "POST",
  "PUT",
  "PATCH",
  "DELETE",
]);

const DEFAULT_BASE = "http://localhost:8000";

function readApiBase(): string {
  const env = (
    import.meta as unknown as { env?: { VITE_API_BASE_URL?: string } }
  ).env;
  return env?.VITE_API_BASE_URL?.replace(/\/+$/, "") ?? DEFAULT_BASE;
}

function readCookie(name: string): string | undefined {
  if (typeof document === "undefined") return undefined;
  const target = `${name}=`;
  for (const raw of document.cookie.split(";")) {
    const c = raw.trim();
    if (c.startsWith(target)) return decodeURIComponent(c.slice(target.length));
  }
  return undefined;
}

type EnvelopeBody = {
  error?: {
    code?: string;
    message?: string;
    details?: unknown;
    request_id?: string;
  };
};

async function parseError(response: Response): Promise<ApiError> {
  let body: EnvelopeBody | undefined;
  try {
    body = (await response.clone().json()) as EnvelopeBody;
  } catch {
    body = undefined;
  }
  const env = body?.error;
  return new ApiError({
    status: response.status,
    code: env?.code ?? "shared.unknown",
    message: env?.message ?? (response.statusText || "Unknown error"),
    details: env?.details ?? null,
    requestId: env?.request_id ?? "",
  });
}

export type ApiFetchOptions = {
  method?: Method;
  body?: unknown;
  /** Override the default mutating-verb idempotency policy. */
  idempotent?: boolean;
  /** Extra request headers (do not include CSRF / Idempotency-Key — the
   *  wrapper sets those itself). */
  headers?: Record<string, string>;
  /** Native `AbortSignal` plumbed through to `fetch`. */
  signal?: AbortSignal;
};

type SuccessOf<
  P extends keyof paths,
  M extends keyof paths[P],
> = paths[P][M] extends {
  responses: infer R;
}
  ? R extends Record<number, infer Rsp>
    ? Rsp extends { content: { "application/json": infer JSON } }
      ? JSON
      : void
    : void
  : void;

export async function apiFetch<
  P extends keyof paths,
  M extends keyof paths[P] = "get" & keyof paths[P],
>(path: P, opts?: ApiFetchOptions): Promise<SuccessOf<P, M>>;

export async function apiFetch(
  path: string,
  opts?: ApiFetchOptions,
): Promise<unknown>;

export async function apiFetch(
  path: string,
  opts: ApiFetchOptions = {},
): Promise<unknown> {
  const method = (opts.method ?? "GET").toUpperCase() as Method;
  const isMutating = MUTATING.has(method);
  const idempotent = opts.idempotent ?? isMutating;

  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(opts.headers ?? {}),
  };

  const init: RequestInit = {
    method,
    credentials: "include",
    ...(opts.signal ? { signal: opts.signal } : {}),
  };

  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }

  if (isMutating) {
    const csrf = readCookie("csrf");
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }

  let descriptor: RequestDescriptor | undefined;
  if (idempotent) {
    descriptor = { method, path, body: opts.body };
    const record = await getOrCreateIdempotencyKey(descriptor);
    headers["Idempotency-Key"] = record.key;
  }

  init.headers = headers;

  const url = `${readApiBase()}${path}`;
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (cause) {
    // Network error — treat as transient; do NOT evict the key so the
    // caller can retry with the same idempotency-key.
    throw new ApiError({
      status: 0,
      code: "shared.network_error",
      message: cause instanceof Error ? cause.message : "Network error",
      details: null,
      requestId: "",
    });
  }

  const isTerminal2xx = response.status >= 200 && response.status < 300;
  const isTerminal4xx = response.status >= 400 && response.status < 500;
  if (descriptor && (isTerminal2xx || isTerminal4xx)) {
    await evictIdempotencyKey(descriptor);
  }

  if (!response.ok) {
    throw await parseError(response);
  }

  if (response.status === 204) return undefined;
  const ctype = response.headers.get("content-type") ?? "";
  if (ctype.includes("application/json")) {
    return (await response.json()) as unknown;
  }
  return await response.text();
}
