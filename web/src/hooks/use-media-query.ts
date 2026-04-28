import { useEffect, useState } from "react";

/** Returns whether `window.matchMedia(query).matches` is currently true.
 *  Falls back to `false` outside the browser. */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState<boolean>(() => {
    if (
      typeof window === "undefined" ||
      typeof window.matchMedia !== "function"
    ) {
      return false;
    }
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (
      typeof window === "undefined" ||
      typeof window.matchMedia !== "function"
    ) {
      return;
    }
    const mq = window.matchMedia(query);
    const handler = (e: MediaQueryListEvent): void => {
      setMatches(e.matches);
    };
    mq.addEventListener("change", handler);
    setMatches(mq.matches);
    return () => {
      mq.removeEventListener("change", handler);
    };
  }, [query]);

  return matches;
}

/** Tailwind `md` breakpoint = 768px. */
export const DESKTOP_QUERY = "(min-width: 768px)";
