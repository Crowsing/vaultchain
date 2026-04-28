/**
 * Sentry capture stub for the admin SPA.
 *
 * Mirrors `web/src/lib/sentry.ts` — V1 ships a no-op so call sites can
 * be written exactly the way they will run in production. The real
 * `@sentry/react` SDK is wired in by a follow-up brief once the
 * `SENTRY_DSN_FRONTEND_ADMIN` build secret is available; until then,
 * `captureException` is a no-op and the exported `init` returns false.
 *
 * The DSN is read from `import.meta.env.VITE_SENTRY_DSN_ADMIN` so the
 * upgrade path is just: install the SDK + replace the body of `init`
 * and `captureException`.
 */

export type SentryCaptureOptions = {
  tags?: Record<string, string>;
};

export const sentry = {
  captureException(_error: unknown, _options?: SentryCaptureOptions): void {
    // intentional no-op in V1
  },
};

export function initSentry(): boolean {
  // intentional no-op in V1; returns false so callers can branch.
  return false;
}
