/**
 * Desktop layout — left sidebar (logo, primary nav, user-card pinned
 * bottom), top header (route title + Search / Ask AI stubs), main
 * content area.
 *
 * AC-phase1-web-005-02: 240px sidebar, NAV's seven items, user-card,
 * active item gets `data-active`, AI item gets `data-ai`.
 */
import type { ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { useUserStore } from "@/store/user-store";

import { NAV } from "./nav";

export function DesktopShell({
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
    <div className="grid h-screen grid-cols-[240px_1fr] bg-bg-page text-text-primary">
      <aside
        data-testid="desktop-sidebar"
        className="flex flex-col border-r border-bg-surface-raised bg-bg-surface p-4"
      >
        <div className="flex items-center gap-2 px-2 py-3 text-lg font-semibold tracking-tight text-brand">
          <div
            aria-hidden
            className="h-6 w-6 rounded-md bg-gradient-to-br from-brand to-cyan-500"
          />
          VaultChain
        </div>
        <nav aria-label="Primary" className="mt-4 flex flex-1 flex-col gap-1">
          {NAV.map((n) => {
            const active = activeId === n.id;
            return (
              <Link
                key={n.id}
                to={n.to}
                data-testid={`desk-nav-${n.id}`}
                data-active={active ? "true" : "false"}
                data-ai={n.ai ? "true" : undefined}
                aria-current={active ? "page" : undefined}
                className="rounded-md px-3 py-2 text-sm text-text-secondary transition-colors hover:bg-bg-surface-raised hover:text-text-primary data-[active=true]:bg-bg-surface-raised data-[active=true]:text-text-primary data-[ai=true]:text-brand"
              >
                {n.label}
              </Link>
            );
          })}
        </nav>
        <div className="mt-4 flex items-center gap-3 rounded-lg bg-bg-surface-raised p-3">
          <div
            aria-hidden
            className="flex h-9 w-9 items-center justify-center rounded-full bg-brand text-text-on-brand"
          >
            {user?.email?.[0]?.toUpperCase() ?? "?"}
          </div>
          <div className="min-w-0 text-sm">
            <div className="truncate font-medium text-text-primary">
              {user?.email ?? "Loading…"}
            </div>
            <div className="text-xs text-text-muted">
              Tier {user?.kyc_tier ?? "—"}
            </div>
          </div>
        </div>
      </aside>

      <main className="flex min-w-0 flex-col">
        <header className="flex items-center justify-between border-b border-bg-surface-raised bg-bg-surface px-6 py-3">
          <h1 className="text-base font-semibold tracking-tight">{title}</h1>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate("/search")}
              aria-label="Search"
            >
              Search
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate("/ai")}
              aria-label="Ask AI"
            >
              Ask AI
            </Button>
            <ThemeToggle />
          </div>
        </header>
        <div className="flex-1 overflow-y-auto p-6">{children}</div>
      </main>
    </div>
  );
}
