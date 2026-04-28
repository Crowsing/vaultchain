/**
 * Top-level <ErrorBoundary>.
 *
 * AC-phase1-web-002-04: unrecognised error codes (or any non-ApiError)
 * render the generic "Something went wrong" UI with the `request_id`
 * shown so a user can paste it into support, and notify the Sentry
 * stub.
 *
 * AC-phase1-web-002-07: render-time errors fall into the same branch;
 * the fallback offers a "Reload" button that calls
 * `window.location.reload()`.
 */
import { Component, type ErrorInfo, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-fetch";
import { isKnownCode, knownCodeMessage } from "@/lib/error-codes";
import { sentry } from "@/lib/sentry";

type Props = { children: ReactNode };
type State = { error: unknown };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: unknown): State {
    return { error };
  }

  componentDidCatch(error: unknown, _info: ErrorInfo): void {
    const requestId = error instanceof ApiError ? error.requestId : "";
    const code = error instanceof ApiError ? error.code : "render_error";
    if (!(error instanceof ApiError) || !isKnownCode(error.code)) {
      sentry.captureException(error, { tags: { request_id: requestId, code } });
    }
  }

  private handleReload = (): void => {
    window.location.reload();
  };

  render(): ReactNode {
    const { error } = this.state;
    if (error === null || error === undefined) return this.props.children;

    if (error instanceof ApiError && isKnownCode(error.code)) {
      return (
        <div role="alert" className="p-4">
          <p className="text-text-primary">{knownCodeMessage(error.code)}</p>
        </div>
      );
    }

    const requestId = error instanceof ApiError ? error.requestId : "";
    return (
      <div
        role="alert"
        className="flex flex-col items-center gap-4 p-8 text-center"
      >
        <h2 className="text-2xl font-semibold text-text-primary">
          Something went wrong
        </h2>
        <p className="max-w-md text-text-secondary">
          An unexpected error occurred. If this keeps happening, share the
          request ID below with support.
        </p>
        {requestId ? (
          <code className="rounded-sm bg-bg-surface-raised px-2 py-1 text-text-primary">
            {requestId}
          </code>
        ) : null}
        <Button onClick={this.handleReload}>Reload</Button>
      </div>
    );
  }
}
