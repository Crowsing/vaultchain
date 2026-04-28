import { AdminShellAuthed } from "@/components/admin-shell";

type PlaceholderProps = {
  queueName: string;
  testId: string;
};

function Placeholder({ queueName, testId }: PlaceholderProps) {
  return (
    <AdminShellAuthed>
      <div
        data-testid={testId}
        className="card"
        style={{
          padding: "32px",
          textAlign: "center",
          background: "var(--bg-surface)",
          borderColor: "var(--border-default)",
        }}
      >
        <h1
          className="text-xl font-semibold"
          style={{ color: "var(--text-primary)" }}
        >
          {queueName}
        </h1>
        <p
          className="text-sm"
          style={{ color: "var(--text-secondary)", marginTop: "8px" }}
        >
          Coming in Phase 3.
        </p>
      </div>
    </AdminShellAuthed>
  );
}

export function ApplicantsPlaceholder() {
  return <Placeholder queueName="Applicants" testId="placeholder-applicants" />;
}

export function TransactionsPlaceholder() {
  return (
    <Placeholder queueName="Transactions" testId="placeholder-transactions" />
  );
}

export function WithdrawalsPlaceholder() {
  return (
    <Placeholder queueName="Withdrawals" testId="placeholder-withdrawals" />
  );
}

export function UsersPlaceholder() {
  return <Placeholder queueName="Users" testId="placeholder-users" />;
}

export function AuditPlaceholder() {
  return <Placeholder queueName="Audit" testId="placeholder-audit" />;
}
