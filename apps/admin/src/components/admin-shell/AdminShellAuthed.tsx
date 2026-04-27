import type { ReactNode } from "react";

type AdminShellAuthedProps = {
  children: ReactNode;
};

export function AdminShellAuthed({ children }: AdminShellAuthedProps) {
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
        <nav aria-label="Admin sections" />
      </aside>
      <header
        data-testid="admin-shell-header"
        className="border-b flex items-center justify-end px-4"
        style={{
          gridArea: "header",
          background: "var(--bg-surface)",
          borderColor: "var(--border-default)",
        }}
      />
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
