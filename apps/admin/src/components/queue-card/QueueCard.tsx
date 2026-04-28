import { useNavigate } from "react-router-dom";

export type QueueCardProps = {
  label: string;
  count: number;
  href: string;
  openLabel: string;
  testId?: string;
};

export function QueueCard({
  label,
  count,
  href,
  openLabel,
  testId,
}: QueueCardProps) {
  const navigate = useNavigate();

  return (
    <div
      data-testid={testId}
      className="card"
      style={{
        padding: "20px",
        background: "var(--bg-surface)",
        borderColor: "var(--border-default)",
        display: "flex",
        flexDirection: "column",
        gap: "12px",
      }}
    >
      <p
        className="text-xs uppercase"
        style={{
          color: "var(--text-secondary)",
          letterSpacing: "0.08em",
          margin: 0,
        }}
      >
        {label}
      </p>
      <p
        data-testid={testId ? `${testId}-count` : undefined}
        className="text-3xl font-semibold"
        style={{ color: "var(--text-primary)", margin: 0 }}
      >
        {count}
      </p>
      <button
        type="button"
        className="btn btn-secondary btn-sm"
        onClick={() => navigate(href)}
        style={{ alignSelf: "flex-start" }}
      >
        {openLabel}
      </button>
    </div>
  );
}
