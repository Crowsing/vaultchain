/**
 * Pre-auth shell — centered card layout used by all `/auth/*` routes.
 * The post-auth shell (web-005's AppShell) is intentionally a separate
 * component tree; the two share only the brand mark.
 */
import type { ReactNode } from "react";

import { ThemeToggle } from "@/components/theme-toggle";

export function AuthLayout({
  title,
  subtitle,
  children,
  testId,
  footer,
}: {
  title?: string;
  subtitle?: string;
  testId: string;
  children: ReactNode;
  footer?: ReactNode;
}): React.JSX.Element {
  return (
    <div className="flex min-h-screen flex-col bg-bg-page text-text-primary">
      <header className="flex items-center justify-between p-4">
        <div className="flex items-center gap-2 text-sm font-semibold tracking-tight text-brand">
          <div
            aria-hidden
            className="h-5 w-5 rounded-md bg-gradient-to-br from-brand to-cyan-500"
          />
          VaultChain
        </div>
        <ThemeToggle />
      </header>
      <main className="flex flex-1 items-center justify-center p-4">
        <section
          data-testid={testId}
          className="w-full max-w-md rounded-lg bg-bg-surface p-6 shadow-md ring-1 ring-border-default md:p-8"
        >
          {title ? (
            <h1 className="mb-2 text-2xl font-semibold tracking-tight text-text-primary">
              {title}
            </h1>
          ) : null}
          {subtitle ? (
            <p className="mb-6 text-sm text-text-secondary">{subtitle}</p>
          ) : null}
          {children}
        </section>
      </main>
      {footer ? (
        <footer className="flex items-center justify-center p-4 text-xs text-text-muted">
          {footer}
        </footer>
      ) : null}
    </div>
  );
}
