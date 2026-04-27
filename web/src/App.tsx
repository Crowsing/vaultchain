import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";

export default function App() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-8 bg-bg-page text-text-primary p-8">
      <header className="flex w-full max-w-2xl items-center justify-between">
        <span className="text-sm font-medium uppercase tracking-wider text-text-muted">
          phase1-web-001
        </span>
        <ThemeToggle />
      </header>
      <main className="flex flex-col items-center gap-4 text-center">
        <h1
          className="text-5xl font-semibold tracking-tight text-brand"
          data-testid="brand-heading"
        >
          VaultChain
        </h1>
        <p className="max-w-md text-text-secondary">
          Custodial multi-chain wallet with an AI assistant. Design tokens are
          wired, Tailwind v4 is wired, fonts are self-hosted, and dark mode
          toggles via
          <code className="mx-1 rounded-sm bg-bg-surface-raised px-1 py-0.5 text-text-primary">
            data-theme
          </code>
          on the document root.
        </p>
        <div className="mt-2 flex gap-2">
          <Button>Primary</Button>
          <Button variant="outline">Secondary</Button>
          <Button variant="ghost">Ghost</Button>
        </div>
      </main>
    </div>
  );
}
