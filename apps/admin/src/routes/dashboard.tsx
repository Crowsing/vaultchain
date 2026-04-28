import { AdminShellAuthed } from "@/components/admin-shell";
import { QueueCard } from "@/components/queue-card";

export default function DashboardRoute() {
  return (
    <AdminShellAuthed>
      <header className="mb-6">
        <h1
          className="text-xl font-semibold"
          style={{ color: "var(--text-primary)" }}
        >
          Dashboard
        </h1>
      </header>
      <section
        data-testid="dashboard-cards"
        className="grid gap-4"
        style={{
          gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
        }}
      >
        <QueueCard
          testId="dashboard-card-kyc"
          label="KYC Queue"
          count={0}
          href="/applicants"
          openLabel="Open queue"
        />
        <QueueCard
          testId="dashboard-card-withdrawals"
          label="Withdrawals Pending"
          count={0}
          href="/withdrawals"
          openLabel="Open queue"
        />
        <QueueCard
          testId="dashboard-card-transactions"
          label="Recent Transactions"
          count={0}
          href="/transactions"
          openLabel="Open list"
        />
        <QueueCard
          testId="dashboard-card-audit"
          label="Audit Events Today"
          count={0}
          href="/audit"
          openLabel="Open log"
        />
      </section>
      <footer className="mt-8" style={{ color: "var(--text-secondary)" }}>
        <p
          data-testid="dashboard-phase-note"
          style={{ fontSize: "8px", opacity: 0.6 }}
        >
          Phase 1 — admin shell
        </p>
      </footer>
    </AdminShellAuthed>
  );
}
