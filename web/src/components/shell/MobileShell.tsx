/**
 * Mobile layout — top header (avatar, page title, settings cog),
 * scrollable body, bottom tab bar with the five tab items from
 * `MOBILE_TABS`.
 *
 * AC-phase1-web-005-03: tap targets ≥44px, Receive/Settings remain
 * navigable via deep links but are absent from the bar.
 */
import type { ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { useUserStore } from "@/store/user-store";

import { MOBILE_TABS, NAV } from "./nav";

const TAB_ITEMS = NAV.filter((n) => MOBILE_TABS.includes(n.id));

export function MobileShell({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}): React.JSX.Element {
  const location = useLocation();
  const navigate = useNavigate();
  const user = useUserStore((s) => s.user);

  const activeId = NAV.find((n) => location.pathname.startsWith(n.to))?.id;

  return (
    <div className="flex h-screen flex-col bg-bg-page text-text-primary">
      <header
        data-testid="mobile-header"
        className="flex items-center justify-between border-b border-bg-surface-raised bg-bg-surface px-4 py-3"
      >
        <button
          type="button"
          onClick={() => navigate("/settings")}
          aria-label="Profile"
          className="flex h-11 w-11 items-center justify-center rounded-full bg-brand text-text-on-brand"
        >
          {user?.email?.[0]?.toUpperCase() ?? "?"}
        </button>
        <h1 className="text-base font-semibold tracking-tight">{title}</h1>
        <button
          type="button"
          onClick={() => navigate("/settings")}
          aria-label="Settings"
          className="flex h-11 w-11 items-center justify-center rounded-md text-text-secondary"
        >
          ⚙
        </button>
      </header>
      <main className="flex-1 overflow-y-auto p-4">{children}</main>
      <nav
        aria-label="Primary"
        data-testid="mobile-tabs"
        className="grid grid-cols-5 border-t border-bg-surface-raised bg-bg-surface"
      >
        {TAB_ITEMS.map((n) => {
          const active = activeId === n.id;
          return (
            <Link
              key={n.id}
              to={n.to}
              data-testid={`mob-tab-${n.id}`}
              data-active={active ? "true" : "false"}
              data-ai={n.ai ? "true" : undefined}
              aria-current={active ? "page" : undefined}
              className="flex h-14 min-h-[44px] flex-col items-center justify-center text-xs text-text-muted transition-colors data-[active=true]:text-text-primary data-[ai=true]:text-brand"
            >
              <span className="text-[10px] uppercase tracking-wider">
                {n.label}
              </span>
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
