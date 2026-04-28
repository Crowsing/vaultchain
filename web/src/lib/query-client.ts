/**
 * Single-tenant TanStack Query client factory.
 *
 * AC-phase1-web-002-06:
 *   • `staleTime` defaults to 30s.
 *   • `retry` retries on network / 5xx, never on 4xx — distinguished
 *     by `ApiError.status` (so `instanceof ApiError` plus the status
 *     range tells us which side of the boundary the failure was on).
 *   • Up to two retries (`failureCount < 2`).
 */
import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "./api-error";

const RETRY_LIMIT = 2;
const STALE_TIME_MS = 30_000;

export function buildQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: STALE_TIME_MS,
        retry: (failureCount, error) =>
          failureCount < RETRY_LIMIT &&
          !(
            error instanceof ApiError &&
            error.status >= 400 &&
            error.status < 500
          ),
      },
    },
  });
}
