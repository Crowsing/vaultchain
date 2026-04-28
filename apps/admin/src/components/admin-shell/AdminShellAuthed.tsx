import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import { adminLogout } from "@/auth/api";
import { useAdminAuthStore } from "@/auth/store";
import { useNavigate } from "react-router-dom";

type AdminShellAuthedProps = {
  children: ReactNode;
};

const NAV_ITEMS: ReadonlyArray<{ label: string; to: string; testId: string }> =
  [
    { label: "Dashboard", to: "/", testId: "nav-dashboard" },
    { label: "Applicants", to: "/applicants", testId: "nav-applicants" },
    { label: "Transactions", to: "/transactions", testId: "nav-transactions" },
    { label: "Withdrawals", to: "/withdrawals", testId: "nav-withdrawals" },
    { label: "Users", to: "/users", testId: "nav-users" },
    { label: "Audit", to: "/audit", testId: "nav-audit" },
  ];

function formatLastLogin(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return null;
    return d.toLocaleString();
  } catch {
    return null;
  }
}

export function AdminShellAuthed({ children }: AdminShellAuthedProps) {
  const user = useAdminAuthStore((s) => s.user);
  const clear = useAdminAuthStore((s) => s.clear);
  const navigate = useNavigate();
  const lastLogin = formatLastLogin(user?.last_login_at ?? null);

  async function onLogout() {
    try {
      await adminLogout();
    } catch {
      // Defensive: clear local state regardless — admins expect logout
      // to be instantaneous even if the network is flaky.
    } finally {
      clear();
      navigate("/login", { replace: true });
    }
  }

  return (
    <div
      data-testid="admin-shell-authed"
      className="min-h-screen grid"
      style={{
        background: "var(--bg-page)",
        gridTemplateColumns: "240px 1fr",
        gridTemplateRows: "56px 1fr",
        gridTemplateAreas: '"sidebar header" "sidebar main"',
      }}
    >
      <aside
        data-testid="admin-shell-sidebar"
        className="border-r"
        style={{
          gridArea: "sidebar",
          background: "var(--bg-surface)",
          borderColor: "var(--border-default)",
        }}
      >
        <div
          className="px-4 py-3 text-sm font-semibold"
          style={{ color: "var(--text-primary)" }}
        >
          VaultChain Admin
        </div>
        <nav aria-label="Admin sections" className="stack">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              data-testid={item.testId}
              className={({ isActive }) =>
                `block px-4 py-2 text-sm ${isActive ? "font-semibold" : ""}`
              }
              style={({ isActive }) => ({
                color: isActive
                  ? "var(--text-primary)"
                  : "var(--text-secondary)",
                background: isActive ? "var(--bg-page)" : "transparent",
              })}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <header
        data-testid="admin-shell-header"
        className="border-b flex items-center justify-end px-4 gap-4"
        style={{
          gridArea: "header",
          background: "var(--bg-surface)",
          borderColor: "var(--border-default)",
        }}
      >
        <div
          className="text-sm flex flex-col items-end"
          data-testid="admin-shell-user"
          style={{ color: "var(--text-secondary)", lineHeight: 1.2 }}
        >
          <span style={{ color: "var(--text-primary)" }}>
            {user?.email ?? ""}
          </span>
          {lastLogin && (
            <span
              data-testid="admin-shell-last-login"
              style={{ fontSize: "11px" }}
            >
              Last sign in: {lastLogin}
            </span>
          )}
        </div>
        <button
          type="button"
          data-testid="admin-logout"
          className="btn btn-secondary btn-sm"
          onClick={onLogout}
        >
          Sign out
        </button>
      </header>
      <main
        data-testid="admin-shell-main"
        className="p-6"
        style={{ gridArea: "main" }}
      >
        {children}
      </main>
    </div>
  );
}
