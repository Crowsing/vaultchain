/**
 * Error type carrying the structured envelope returned by every
 * VaultChain HTTP endpoint per `phase1-shared-005`.
 *
 * AC-phase1-web-002-03: components catch by `code`, never by string
 * match on `message`. The status code is exposed so the TanStack
 * retry policy in `buildQueryClient` can distinguish 4xx from 5xx
 * (AC-phase1-web-002-06).
 */
export type ApiErrorInit = {
  status: number;
  code: string;
  message: string;
  details: unknown;
  requestId: string;
};

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  readonly requestId: string;

  constructor(init: ApiErrorInit) {
    super(init.message);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.details = init.details;
    this.requestId = init.requestId;
    Object.setPrototypeOf(this, ApiError.prototype);
  }
}
