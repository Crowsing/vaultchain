/**
 * Persistent idempotency-key store backed by IndexedDB.
 *
 * AC-phase1-web-002-02: every mutating request gets an `Idempotency-Key`
 * header. AC-phase1-web-002-05: the same key is reused for retries of
 * the same `(method, path, body-hash)` until the response is terminal
 * (any 2xx or 4xx) — terminal evicts the record so a logically new
 * request can mint a fresh key.
 *
 * Body hashing uses a stable JSON-serialiser that sorts object keys at
 * every level. The matching backend middleware (`phase1-shared-006`)
 * treats the key as opaque; the front-end is responsible for assigning
 * the same key to genuinely-equal retries.
 */
import { del, get, set } from "idb-keyval";
import { v4 as uuidv4 } from "uuid";

export type IdempotencyRecord = {
  key: string;
  /** True once a 2xx/4xx terminal response has been observed and the
   *  record is on its way to deletion. The flag is briefly observable
   *  during eviction; production code never reads it. */
  resolved: boolean;
};

export type RequestDescriptor = {
  method: string;
  path: string;
  body: unknown;
};

const STORE_PREFIX = "idempotency:";

function stableStringify(v: unknown): string {
  if (v === null || typeof v !== "object") return JSON.stringify(v);
  if (Array.isArray(v)) {
    return `[${v.map(stableStringify).join(",")}]`;
  }
  const obj = v as Record<string, unknown>;
  const keys = Object.keys(obj).sort();
  return `{${keys
    .map((k) => `${JSON.stringify(k)}:${stableStringify(obj[k])}`)
    .join(",")}}`;
}

function djb2Hex(s: string): string {
  let h = 5381;
  for (let i = 0; i < s.length; i += 1) {
    h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
  }
  return h.toString(16).padStart(8, "0");
}

function bodyHash(body: unknown): string {
  return djb2Hex(stableStringify(body ?? null));
}

function storeKey(req: RequestDescriptor): string {
  return `${STORE_PREFIX}${req.method.toUpperCase()}:${req.path}:${bodyHash(req.body)}`;
}

/** Generate a fresh UUIDv4 (exposed for tests / callers that need to
 *  pre-mint a key for non-fetch use, e.g. SSE init). */
export function newIdempotencyKey(): string {
  return uuidv4();
}

/** Read the stored record, if any, without mutating it. */
export async function peekIdempotencyKey(
  req: RequestDescriptor,
): Promise<IdempotencyRecord | undefined> {
  return get<IdempotencyRecord>(storeKey(req));
}

/** Return the existing key for this request, or persist a freshly
 *  generated one. The record is marked unresolved until evicted by
 *  `evictIdempotencyKey` (or replaced by another mint after eviction). */
export async function getOrCreateIdempotencyKey(
  req: RequestDescriptor,
): Promise<IdempotencyRecord> {
  const k = storeKey(req);
  const existing = await get<IdempotencyRecord>(k);
  if (existing && !existing.resolved) return existing;
  const fresh: IdempotencyRecord = {
    key: newIdempotencyKey(),
    resolved: false,
  };
  await set(k, fresh);
  return fresh;
}

/** Drop the record. Called on terminal responses (2xx or 4xx). */
export async function evictIdempotencyKey(
  req: RequestDescriptor,
): Promise<void> {
  await del(storeKey(req));
}
