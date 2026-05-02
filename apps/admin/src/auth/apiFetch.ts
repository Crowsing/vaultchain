import { getAdminCsrfToken } from "./csrf";
import { ApiError, type ErrorEnvelope } from "./types";

// Admin SPA and the FastAPI app live on different subdomains in production
// (admin.<domain> vs api.<domain>), so calls must be absolute. Dev keeps the
// relative form so the Vite proxy in vite.config.ts forwards to localhost:8000.
function readApiBase(): string {
  const env = (
    import.meta as unknown as { env?: { VITE_API_BASE_URL?: string } }
  ).env;
  const base = env?.VITE_API_BASE_URL?.replace(/\/+$/, "") ?? "";
  return `${base}/admin/api/v1`;
}

const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

type ApiFetchOptions = {
  method?: string;
  body?: unknown;
  idempotencyKey?: string;
  signal?: AbortSignal;
};

function generateUuidV4(): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  // jsdom fallback for tests where crypto is unavailable.
  const bytes = new Uint8Array(16);
  for (let i = 0; i < bytes.length; i += 1)
    bytes[i] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6]! & 0x0f) | 0x40;
  bytes[8] = (bytes[8]! & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10, 16).join("")}`;
}

function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (!value || typeof value !== "object") return false;
  const err = (value as { error?: unknown }).error;
  if (!err || typeof err !== "object") return false;
  const e = err as { code?: unknown; message?: unknown };
  return typeof e.code === "string" && typeof e.message === "string";
}

export async function adminApiFetch<T = unknown>(
  path: string,
  opts: ApiFetchOptions = {},
): Promise<T> {
  const method = (opts.method ?? "GET").toUpperCase();
  const headers = new Headers();
  headers.set("Accept", "application/json");

  let bodyText: string | undefined;
  if (opts.body !== undefined) {
    headers.set("Content-Type", "application/json");
    bodyText = JSON.stringify(opts.body);
  }

  if (MUTATING_METHODS.has(method)) {
    const csrf = getAdminCsrfToken();
    if (csrf) headers.set("X-CSRF-Token", csrf);
    if (method === "POST") {
      headers.set("X-Idempotency-Key", opts.idempotencyKey ?? generateUuidV4());
    }
  }

  const base = readApiBase();
  const url = path.startsWith("/") ? `${base}${path}` : `${base}/${path}`;
  const init: RequestInit = {
    method,
    headers,
    credentials: "include",
  };
  if (bodyText !== undefined) init.body = bodyText;
  if (opts.signal) init.signal = opts.signal;

  const response = await fetch(url, init);
  if (response.status === 204) return undefined as T;

  const text = await response.text();
  let parsed: unknown = undefined;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = undefined;
    }
  }

  if (!response.ok) {
    if (isErrorEnvelope(parsed)) {
      const e = parsed.error;
      throw new ApiError({
        status: response.status,
        code: e.code,
        message: e.message,
        details: e.details ?? {},
        requestId: e.request_id ?? "",
      });
    }
    throw new ApiError({
      status: response.status,
      code: "internal.unexpected",
      message: "Something went wrong, try again.",
    });
  }

  return parsed as T;
}
