import type { ReactNode } from "react";

type AdminShellEmptyProps = {
  children: ReactNode;
};

export function AdminShellEmpty({ children }: AdminShellEmptyProps) {
  return (
    <div
      data-testid="admin-shell-empty"
      className="min-h-screen flex items-center justify-center px-4 py-12"
      style={{ background: "var(--bg-page)" }}
    >
      <main className="w-full max-w-sm">{children}</main>
    </div>
  );
}
