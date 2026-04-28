/**
 * Responsive switcher — picks DesktopShell or MobileShell based on
 * viewport width. The active route's `<Outlet />` renders inside.
 *
 * AC-phase1-web-005-02 / AC-phase1-web-005-03 ride on this; the
 * media query reads from `useMediaQuery(DESKTOP_QUERY)` so the
 * test suite can drive the switch via `vi.stubGlobal("matchMedia", …)`.
 */
import { Outlet, useLocation } from "react-router-dom";

import { DESKTOP_QUERY, useMediaQuery } from "@/hooks/use-media-query";

import { DesktopShell } from "./DesktopShell";
import { MobileShell } from "./MobileShell";
import { NAV } from "./nav";

function titleForPath(pathname: string): string {
  for (const n of NAV) {
    if (pathname === n.to || pathname.startsWith(`${n.to}/`)) return n.label;
  }
  return "VaultChain";
}

export function AppShell(): React.JSX.Element {
  const isDesktop = useMediaQuery(DESKTOP_QUERY);
  const location = useLocation();
  const title = titleForPath(location.pathname);

  if (isDesktop) {
    return (
      <DesktopShell title={title}>
        <Outlet />
      </DesktopShell>
    );
  }
  return (
    <MobileShell title={title}>
      <Outlet />
    </MobileShell>
  );
}
