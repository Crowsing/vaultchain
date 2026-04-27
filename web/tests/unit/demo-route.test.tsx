import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { render, cleanup } from "@testing-library/react";
import App from "@/App";

beforeEach(() => {
  document.documentElement.removeAttribute("data-theme");
  window.localStorage.clear();
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockReturnValue({
      matches: false,
      media: "(prefers-color-scheme: dark)",
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Demo route (App)", () => {
  it("renders the brand heading", () => {
    const { getByTestId } = render(<App />);
    expect(getByTestId("brand-heading").textContent).toBe("VaultChain");
  });

  it("matches the bootstrap surface snapshot", () => {
    const { container } = render(<App />);
    expect(container).toMatchSnapshot();
  });
});
