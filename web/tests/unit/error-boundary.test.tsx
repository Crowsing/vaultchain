// Unit tests for the top-level <ErrorBoundary>. Covers
//   - AC-phase1-web-002-04: unrecognized error code → generic UI +
//     request_id + Sentry stub.
//   - AC-phase1-web-002-07: render error → fallback UI with Reload.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ErrorBoundary } from "@/components/error-boundary";
import { ApiError } from "@/lib/api-fetch";
import { sentry } from "@/lib/sentry";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

beforeEach(() => {
  // React logs uncaught render errors to console.error; suppress for
  // test ergonomics (the assertion-driving expectation is the rendered
  // fallback, not the noise).
  vi.spyOn(console, "error").mockImplementation(() => {});
});

function Boom({ what }: { what: Error }): React.JSX.Element {
  throw what;
}

describe("ErrorBoundary", () => {
  it("error_boundary_renders_fallback_on_render_error", async () => {
    render(
      <ErrorBoundary>
        <Boom what={new Error("oops")} />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/Something went wrong/i)).toBeInTheDocument();
    const reload = screen.getByRole("button", { name: /reload/i });
    expect(reload).toBeInTheDocument();
  });

  it("error_boundary_reload_button_calls_window_location_reload", async () => {
    const reloadSpy = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, reload: reloadSpy },
    });

    render(
      <ErrorBoundary>
        <Boom what={new Error("kaboom")} />
      </ErrorBoundary>,
    );
    await userEvent.click(screen.getByRole("button", { name: /reload/i }));
    expect(reloadSpy).toHaveBeenCalledTimes(1);
  });

  it("error_boundary_shows_request_id_for_unknown_apierror", () => {
    const captureSpy = vi.spyOn(sentry, "captureException");
    const apiErr = new ApiError({
      status: 500,
      code: "shared.upstream",
      message: "downstream broken",
      details: null,
      requestId: "req-XYZ-99",
    });

    render(
      <ErrorBoundary>
        <Boom what={apiErr} />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/Something went wrong/i)).toBeInTheDocument();
    expect(screen.getByText("req-XYZ-99")).toBeInTheDocument();
    expect(captureSpy).toHaveBeenCalledTimes(1);
    expect(captureSpy.mock.calls[0]![1]).toEqual({
      tags: { request_id: "req-XYZ-99", code: "shared.upstream" },
    });
  });

  it("error_boundary_renders_recognized_codes_via_known_message", () => {
    const apiErr = new ApiError({
      status: 401,
      code: "identity.unauthenticated",
      message: "Please sign in",
      details: null,
      requestId: "req-known-1",
    });

    render(
      <ErrorBoundary>
        <Boom what={apiErr} />
      </ErrorBoundary>,
    );
    // Recognized code shows the registry-mapped human copy, not the
    // generic "Something went wrong" text.
    expect(screen.getByText(/please sign in/i)).toBeInTheDocument();
    expect(screen.queryByText(/Something went wrong/i)).not.toBeInTheDocument();
  });
});
