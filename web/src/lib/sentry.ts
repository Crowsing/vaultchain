/**
 * Sentry capture stub.
 *
 * V1 ships with a no-op so call sites can be written exactly the way
 * they will be in production. The deploy brief replaces the body with
 * the real `@sentry/browser` `captureException` call.
 *
 * AC-phase1-web-002-04: the top-level error boundary calls
 * `sentry.captureException(error, { tags: { request_id, code } })`.
 */

// TODO(deploy): wire Sentry SDK — replace this no-op with
// `Sentry.captureException(error, options)`.

export type SentryCaptureOptions = {
  tags?: Record<string, string>;
};

export const sentry = {
  captureException(_error: unknown, _options?: SentryCaptureOptions): void {
    // intentional no-op in V1
  },
};
