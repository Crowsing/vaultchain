/**
 * Reusable placeholder card — used by every authed route in this brief
 * (the real screens land in subsequent briefs).
 */
export function PlaceholderRoute({
  title,
  description,
  testId,
}: {
  title: string;
  description: string;
  testId: string;
}): React.JSX.Element {
  return (
    <div
      className="rounded-lg bg-bg-surface p-8 text-center"
      data-testid={testId}
    >
      <h2 className="text-lg font-semibold text-text-primary">{title}</h2>
      <p className="mt-2 text-sm text-text-secondary">{description}</p>
    </div>
  );
}
